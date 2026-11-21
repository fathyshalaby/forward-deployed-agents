/**
 * Product-owned MCP server (stdio by default).
 * No separate FDA process — FDE tools run here next to product connectors.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import {
  ControlPlane,
  toolCatalog,
  toolHandlers,
} from "./control-plane.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

const plane = new ControlPlane({
  agentId: "specky.customer-fde",
  agentName: "Specky Customer FDE",
  playbooksDir: join(root, "playbooks"),
  artifactsDir: join(root, "artifacts"),
  root,
});
const handlers = toolHandlers(plane);
const catalog = toolCatalog();

type JsonRpc = {
  jsonrpc?: string;
  id?: string | number | null;
  method?: string;
  params?: Record<string, unknown>;
};

async function handle(message: JsonRpc): Promise<object | null> {
  if (message.method?.startsWith("notifications/")) return null;
  const id = message.id ?? null;
  const method = message.method || "";
  const params = message.params || {};

  try {
    if (method === "initialize") {
      return {
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: params.protocolVersion || "2024-11-05",
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "product-fda-mcp", version: "0.1.0" },
          instructions:
            "Product-owned forward-deployed agent MCP. Plan with play.plan, human grants approvals out-of-band, then play.run. Artifacts are read-only.",
        },
      };
    }
    if (method === "ping") return { jsonrpc: "2.0", id, result: {} };
    if (method === "tools/list") {
      return { jsonrpc: "2.0", id, result: { tools: catalog } };
    }
    if (method === "tools/call") {
      const name = String(params.name || "");
      const args = (params.arguments || {}) as Record<string, unknown>;
      const handler = handlers[name];
      if (!handler) {
        return {
          jsonrpc: "2.0",
          id,
          result: {
            isError: true,
            content: [{ type: "text", text: `unknown tool: ${name}` }],
          },
        };
      }
      const result = await handler(args);
      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify(result) }],
        },
      };
    }
    return {
      jsonrpc: "2.0",
      id,
      error: { code: -32601, message: `Method not found: ${method}` },
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      jsonrpc: "2.0",
      id,
      result: {
        isError: true,
        content: [{ type: "text", text: msg }],
      },
    };
  }
}

async function stdioLoop() {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let message: JsonRpc;
    try {
      message = JSON.parse(trimmed) as JsonRpc;
    } catch {
      continue;
    }
    const response = await handle(message);
    if (response && message.id !== undefined) {
      process.stdout.write(JSON.stringify(response) + "\n");
    }
  }
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function httpLoop(port: number) {
  const token = process.env.FDA_MCP_TOKEN || "";
  const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
    if (req.url === "/health") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }
    if (token) {
      const auth = req.headers.authorization || "";
      if (auth !== `Bearer ${token}`) {
        res.writeHead(401).end("unauthorized");
        return;
      }
    }
    if (req.method === "POST" && (req.url === "/mcp" || req.url === "/")) {
      const raw = await readBody(req);
      const message = JSON.parse(raw) as JsonRpc;
      const response = await handle(message);
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(response));
      return;
    }
    res.writeHead(404).end("not found");
  });
  server.listen(port, "0.0.0.0", () => {
    console.error(`product FDA MCP http on :${port}/mcp`);
  });
}

if (process.argv.includes("--http")) {
  await httpLoop(Number(process.env.PORT || 8000));
} else {
  await stdioLoop();
}
