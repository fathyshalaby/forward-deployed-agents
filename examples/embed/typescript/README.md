# Embed FDA tools in a product MCP (TypeScript)

Copy this folder into a product repo (or port the handlers into an existing
MCP server). Customers connect Claude / ChatGPT to **this** process — not a
separate FDA deploy.

```sh
cd examples/embed/typescript
npm install
npm run start          # stdio MCP for Claude Desktop / Code
# npm run start:http   # optional HTTP/SSE for ChatGPT-style remote MCP
```

Claude Desktop snippet:

```json
{
  "mcpServers": {
    "specky-fde": {
      "command": "node",
      "args": ["/ABS/PATH/to/examples/embed/typescript/dist/server.js"]
    }
  }
}
```

Playbooks live in `./playbooks` (Specky-shaped sample included). Replace
connector handlers in `connectors.ts` with real product calls.
