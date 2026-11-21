# Specky Customer FDE (example)

Flagship example: a forward-deployed agent for a product like Specky.
Customers talk to it through Claude or ChatGPT. It onboards a workspace and
diagnoses or fixes integrations — with human approval on every write.

```sh
fda agents validate examples/bundles/specky-fde
fda agents build examples/bundles/specky-fde -o examples/bundles/dist/specky.customer-fde-0.1.0.fda
fda agents install examples/bundles/dist/specky.customer-fde-0.1.0.fda
fda agents list
```

Plays (after install):

- `specky.customer-fde::onboard`
- `specky.customer-fde::integration_fix`

Connector results are simulated until the product registers signed webhook
handlers (see `docs/boilerplate.md`).
