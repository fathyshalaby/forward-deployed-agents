/** Declarative playbook + connector shapes (same ideas as fda-agent/v1). */

export type DataNeed = "aggregate" | "metadata" | "identifier" | "content";

export interface PlayStep {
  id: string;
  title: string;
  tool: "connectors.call" | "note";
  connector?: string;
  action?: string;
  scopes?: string[];
  needs?: DataNeed[];
  write?: boolean;
  purpose?: string;
}

export interface Playbook {
  id: string;
  name: string;
  description: string;
  purpose: string;
  steps: PlayStep[];
}

export interface Connector {
  id: string;
  name: string;
  scopes: string[];
  actions: string[];
  approval_required?: string[];
  description?: string;
}

export interface Approval {
  id: string;
  action: string;
  purpose: string;
  needs: DataNeed[];
  status: "pending" | "granted" | "denied" | "used";
  approver?: string;
}
