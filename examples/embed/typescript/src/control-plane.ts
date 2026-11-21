/**
 * Minimal FDE control plane hosted inside the product MCP.
 * Policy: plan → human approval → run → content-free audit. Fail closed.
 */
import { createHash, randomBytes } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { callConnector, CONNECTORS } from "./connectors.js";
import type { Approval, Playbook, PlayStep } from "./types.js";

function newId(prefix: string): string {
  return prefix + randomBytes(6).toString("hex");
}

function hashText(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export class ControlPlane {
  readonly agentId: string;
  readonly agentName: string;
  private playbooks = new Map<string, Playbook>();
  private approvals = new Map<string, Approval>();
  private runs = new Map<string, Record<string, unknown>>();
  private audit: Record<string, unknown>[] = [];
  private paused = false;
  private readonly root: string;

  constructor(opts: {
    agentId: string;
    agentName: string;
    playbooksDir: string;
    artifactsDir?: string;
    root: string;
  }) {
    this.agentId = opts.agentId;
    this.agentName = opts.agentName;
    this.root = opts.root;
    for (const file of readdirSync(opts.playbooksDir)) {
      if (!file.endsWith(".json")) continue;
      const play = JSON.parse(
        readFileSync(join(opts.playbooksDir, file), "utf8"),
      ) as Playbook;
      this.playbooks.set(`${opts.agentId}::${play.id}`, play);
    }
    this.artifactsDir = opts.artifactsDir;
  }

  private artifactsDir?: string;

  listAgents() {
    return {
      agents: [
        {
          id: this.agentId,
          name: this.agentName,
          playbook_ids: [...this.playbooks.keys()],
          connectors: CONNECTORS.map((c) => `${this.agentId}::${c.id}`),
        },
      ],
      count: 1,
    };
  }

  listPlays() {
    return {
      plays: [...this.playbooks.entries()].map(([id, play]) => ({
        id,
        name: play.name,
        description: play.description,
        purpose: play.purpose,
        steps: play.steps.length,
      })),
    };
  }

  describe(playId: string) {
    const play = this.requirePlay(playId);
    return { ...play, id: playId };
  }

  plan(playId: string) {
    const play = this.requirePlay(playId);
    const steps = play.steps.map((step) => {
      const needsApproval = Boolean(step.write);
      let approval_id = "";
      if (needsApproval) {
        const id = newId("a");
        this.approvals.set(id, {
          id,
          action: step.action || step.id,
          purpose: step.purpose || play.purpose,
          needs: step.needs || ["metadata"],
          status: "pending",
        });
        approval_id = id;
      }
      return {
        id: step.id,
        title: step.title,
        connector: step.connector,
        action: step.action,
        scopes: step.scopes || [],
        needs: step.needs || [],
        write: Boolean(step.write),
        approval_required: needsApproval,
        approval_id,
      };
    });
    this.record("play.plan", "allow", { play_id: playId });
    return {
      play_id: playId,
      purpose: play.purpose,
      playbook_hash: hashText(JSON.stringify(play)),
      steps,
      next: "Human grants each approval_id out-of-band, then call play.run.",
    };
  }

  /** Human-only in production. Exposed for local demo / product approval UI. */
  grant(approvalId: string, approver: string) {
    const approval = this.approvals.get(approvalId);
    if (!approval) throw new Error("unknown approval");
    if (approval.status !== "pending") throw new Error(approval.status);
    approval.status = "granted";
    approval.approver = approver;
    this.record("approval.grant", "allow", {
      approval_id: approvalId,
      approver_hash: hashText(approver),
    });
    return { approval_id: approvalId, status: "granted", approver };
  }

  approvalStatus(approvalId: string) {
    const approval = this.approvals.get(approvalId);
    if (!approval) throw new Error("unknown approval");
    return { ...approval };
  }

  async run(playId: string, approvals: Record<string, string> = {}) {
    if (this.paused) throw new Error("kill switch active");
    const play = this.requirePlay(playId);
    const runId = newId("r");
    const results: Record<string, unknown>[] = [];

    for (const step of play.steps) {
      if (step.write) {
        const approvalId = approvals[step.id];
        if (!approvalId) {
          this.record("play.run", "deny", {
            play_id: playId,
            step_id: step.id,
            reason: "missing_approval",
          });
          const denied = {
            run_id: runId,
            status: "denied",
            step_id: step.id,
            reason: "missing_approval",
            results,
          };
          this.runs.set(runId, denied);
          return denied;
        }
        const approval = this.approvals.get(approvalId);
        if (!approval || approval.status !== "granted") {
          this.record("play.run", "deny", {
            play_id: playId,
            step_id: step.id,
            reason: "approval_not_granted",
          });
          const denied = {
            run_id: runId,
            status: "denied",
            step_id: step.id,
            reason: "approval_not_granted",
            results,
          };
          this.runs.set(runId, denied);
          return denied;
        }
        approval.status = "used";
      }

      if (step.tool === "note") {
        results.push({ step_id: step.id, status: "ok", result: { note: true } });
        continue;
      }

      const result = await callConnector(
        step.connector || "",
        step.action || "",
        step.scopes || ["read"],
      );
      results.push({ step_id: step.id, status: "ok", result });
      this.record("connectors.call", "allow", {
        play_id: playId,
        step_id: step.id,
        action: step.action,
      });
    }

    const complete = { run_id: runId, status: "complete", results };
    this.runs.set(runId, complete);
    this.record("play.run", "allow", { play_id: playId, run_id: runId });
    return complete;
  }

  status(runId: string) {
    const run = this.runs.get(runId);
    if (!run) throw new Error("unknown run");
    return run;
  }

  listArtifacts() {
    if (!this.artifactsDir) return { artifacts: [], count: 0 };
    const artifacts = readdirSync(this.artifactsDir)
      .filter((f) => f.endsWith(".md"))
      .map((f) => {
        const id = f.replace(/\.md$/, "");
        const text = readFileSync(join(this.artifactsDir!, f), "utf8");
        const titleLine = text.split("\n").find((l) => l.startsWith("# "));
        return {
          id,
          title: titleLine ? titleLine.slice(2).trim() : id,
          agent_id: this.agentId,
          path: `artifacts/${f}`,
        };
      });
    return { artifacts, count: artifacts.length };
  }

  getArtifact(artifactId: string) {
    if (!this.artifactsDir) throw new Error("no artifacts");
    const safe = artifactId.replace(/[^a-z0-9._-]/gi, "");
    if (safe !== artifactId) throw new Error("invalid artifact id");
    const path = join(this.artifactsDir, `${safe}.md`);
    const recipe = readFileSync(path, "utf8");
    return {
      id: safe,
      agent_id: this.agentId,
      recipe,
      note: "Build as a Claude artifact on THIS product MCP. Read-only from the artifact; writes via play.plan → human approval → play.run in chat.",
    };
  }

  auditExplain(limit = 30) {
    return { entries: this.audit.slice(-limit), count: this.audit.length };
  }

  opsStatus() {
    return {
      paused: this.paused,
      agent_id: this.agentId,
      approvals: this.approvals.size,
      runs: this.runs.size,
      audit: this.audit.length,
    };
  }

  pause(reason: string) {
    this.paused = true;
    this.record("ops.pause", "allow", { reason_hash: hashText(reason) });
    return { paused: true };
  }

  resume() {
    this.paused = false;
    this.record("ops.resume", "allow", {});
    return { paused: false };
  }

  private requirePlay(playId: string): Playbook {
    const play = this.playbooks.get(playId);
    if (!play) throw new Error(`unknown play: ${playId}`);
    return play;
  }

  private record(tool: string, decision: string, meta: Record<string, unknown>) {
    this.audit.push({
      seq: this.audit.length + 1,
      ts: new Date().toISOString(),
      tool,
      decision,
      ...meta,
    });
  }
}

export type ToolHandler = (args: Record<string, unknown>) => Promise<unknown> | unknown;

export function toolHandlers(plane: ControlPlane): Record<string, ToolHandler> {
  return {
    "agents.list": () => plane.listAgents(),
    "agent.describe": (args) => {
      const agents = plane.listAgents().agents;
      const hit = agents.find((a) => a.id === args.agent_id);
      if (!hit) throw new Error("unknown agent");
      return hit;
    },
    "plays.list": () => plane.listPlays(),
    "play.describe": (args) => plane.describe(String(args.play_id)),
    "play.plan": (args) => plane.plan(String(args.play_id)),
    "play.run": (args) =>
      plane.run(
        String(args.play_id),
        (args.approvals as Record<string, string>) || {},
      ),
    "play.status": (args) => plane.status(String(args.run_id)),
    "approval.status": (args) => plane.approvalStatus(String(args.approval_id)),
    // Demo only — wire your product approval UI to plane.grant; do not expose to the model in prod.
    "approval.grant_demo": (args) =>
      plane.grant(String(args.approval_id), String(args.approver || "human")),
    "audit.explain": (args) =>
      plane.auditExplain(Number(args.limit || 30)),
    "ops.status": () => plane.opsStatus(),
    "artifacts.list": () => plane.listArtifacts(),
    "artifacts.get": (args) =>
      plane.getArtifact(String(args.artifact_id)),
  };
}

export function toolCatalog(): { name: string; description: string; inputSchema: object; annotations: object }[] {
  const read = { readOnlyHint: true, destructiveHint: false, openWorldHint: false };
  const write = { readOnlyHint: false, destructiveHint: true, openWorldHint: false };
  return [
    { name: "agents.list", description: "List FDE agents on this product MCP.", inputSchema: { type: "object", properties: {} }, annotations: read },
    { name: "agent.describe", description: "Describe one agent.", inputSchema: { type: "object", properties: { agent_id: { type: "string" } }, required: ["agent_id"] }, annotations: read },
    { name: "plays.list", description: "List playbooks.", inputSchema: { type: "object", properties: {} }, annotations: read },
    { name: "play.describe", description: "Show play steps before running.", inputSchema: { type: "object", properties: { play_id: { type: "string" } }, required: ["play_id"] }, annotations: read },
    { name: "play.plan", description: "Issue approval ids; executes nothing.", inputSchema: { type: "object", properties: { play_id: { type: "string" } }, required: ["play_id"] }, annotations: read },
    { name: "play.run", description: "Run a play with step→approval map. Fails closed.", inputSchema: { type: "object", properties: { play_id: { type: "string" }, approvals: { type: "object" } }, required: ["play_id"] }, annotations: write },
    { name: "play.status", description: "Previous run result.", inputSchema: { type: "object", properties: { run_id: { type: "string" } }, required: ["run_id"] }, annotations: read },
    { name: "approval.status", description: "Read approval status.", inputSchema: { type: "object", properties: { approval_id: { type: "string" } }, required: ["approval_id"] }, annotations: read },
    { name: "approval.grant_demo", description: "DEMO ONLY human grant. Replace with product approval UI in production.", inputSchema: { type: "object", properties: { approval_id: { type: "string" }, approver: { type: "string" } }, required: ["approval_id"] }, annotations: write },
    { name: "audit.explain", description: "Content-free audit trail.", inputSchema: { type: "object", properties: { limit: { type: "number" } } }, annotations: read },
    { name: "ops.status", description: "Kill switch and counters.", inputSchema: { type: "object", properties: {} }, annotations: read },
    { name: "artifacts.list", description: "Claude artifact recipes.", inputSchema: { type: "object", properties: {} }, annotations: read },
    { name: "artifacts.get", description: "One artifact recipe markdown.", inputSchema: { type: "object", properties: { artifact_id: { type: "string" } }, required: ["artifact_id"] }, annotations: read },
  ];
}

// silence unused in types re-export path
export type { PlayStep };
