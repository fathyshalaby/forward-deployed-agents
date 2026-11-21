/**
 * Product-side connector handlers. Replace these with real Specky/product calls
 * that use credentials already in the product secret store.
 */
import type { Connector } from "./types.js";

export const CONNECTORS: Connector[] = [
  {
    id: "workspace",
    name: "Product workspace",
    scopes: ["read"],
    actions: ["workspace.status", "workspace.checklist"],
    description: "Aggregate workspace health and onboarding checklist.",
  },
  {
    id: "integrations",
    name: "Integrations",
    scopes: ["read", "write"],
    actions: [
      "integrations.list",
      "integrations.status",
      "integrations.diagnose",
      "integrations.reconnect",
      "integrations.trigger_sync",
    ],
    approval_required: ["integrations.reconnect", "integrations.trigger_sync"],
    description: "List/diagnose; reconnect or re-sync only after human approval.",
  },
  {
    id: "support",
    name: "Support handoff",
    scopes: ["read", "write"],
    actions: ["support.open_ticket"],
    approval_required: ["support.open_ticket"],
    description: "Metadata-only handoff ticket.",
  },
];

/** Simulated results — swap for real product APIs. */
export async function callConnector(
  connectorId: string,
  action: string,
  scopes: string[],
): Promise<Record<string, unknown>> {
  const connector = CONNECTORS.find((c) => c.id === connectorId);
  if (!connector) throw new Error(`connector not granted: ${connectorId}`);
  if (!connector.actions.includes(action)) {
    throw new Error(`action not granted: ${action}`);
  }
  if (!scopes.every((s) => connector.scopes.includes(s))) {
    throw new Error("scope not granted");
  }
  // ponytail: in-process product call goes here (no separate FDA webhook)
  switch (action) {
    case "workspace.status":
      return { ok: true, healthy: true, mode: "product" };
    case "workspace.checklist":
      return { ok: true, steps_done: 2, steps_total: 5, mode: "product" };
    case "integrations.list":
      return { ok: true, connected: 3, missing: 2, mode: "product" };
    case "integrations.status":
      return { ok: true, state: "error", code: "oauth_expired", mode: "product" };
    case "integrations.diagnose":
      return { ok: true, fix: "reconnect", mode: "product" };
    case "integrations.reconnect":
      return { ok: true, reconnected: true, mode: "product" };
    case "integrations.trigger_sync":
      return { ok: true, sync_started: true, mode: "product" };
    case "support.open_ticket":
      return { ok: true, created: true, ref: "T-100", mode: "product" };
    default:
      return { ok: true, mode: "product" };
  }
}
