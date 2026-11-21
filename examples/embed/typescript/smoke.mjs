/** Smoke the control plane without a full MCP client. */
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = dirname(fileURLToPath(import.meta.url));
const build = spawnSync("npx", ["--yes", "tsc", "-p", "tsconfig.json"], {
  cwd: root,
  encoding: "utf8",
});
if (build.status !== 0) {
  console.error(build.stdout, build.stderr);
  process.exit(1);
}

const require = createRequire(import.meta.url);
// Dynamic import compiled ESM
const { ControlPlane } = await import("./dist/control-plane.js");

const plane = new ControlPlane({
  agentId: "specky.customer-fde",
  agentName: "Specky Customer FDE",
  playbooksDir: join(root, "playbooks"),
  artifactsDir: join(root, "artifacts"),
  root,
});

const plan = plane.plan("specky.customer-fde::onboard");
const approvals = {};
for (const step of plan.steps) {
  if (step.approval_id) {
    plane.grant(step.approval_id, "smoke-human");
    approvals[step.id] = step.approval_id;
  }
}
const run = await plane.run("specky.customer-fde::onboard", approvals);
const arts = plane.listArtifacts();
if (run.status !== "complete") {
  console.error(run);
  process.exit(1);
}
console.log(
  JSON.stringify(
    {
      status: run.status,
      run_id: run.run_id,
      artifacts: arts.count,
      ops: plane.opsStatus(),
    },
    null,
    2,
  ),
);
