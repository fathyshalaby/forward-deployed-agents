# Specky Customer FDE (example)

Flagship **declarative** example for a product like Specky: onboard +
integration fix + Claude artifact recipe.

**Preferred:** load these playbooks into the product MCP scaffold
(`examples/embed/typescript/`) so customers hit Specky's MCP, not a separate
FDA process. See `docs/embed_mcp.md`.

Optional Python reference:

```sh
fda agents validate examples/bundles/specky-fde
fda agents build examples/bundles/specky-fde -o examples/bundles/dist/specky.customer-fde-0.1.0.fda
fda agents install examples/bundles/dist/specky.customer-fde-0.1.0.fda
```

Plays: `specky.customer-fde::onboard`, `specky.customer-fde::integration_fix`.
