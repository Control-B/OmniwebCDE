# Known limitations

This repository delivers a working local product slice and secure control-plane core. It
does not claim that a real DigitalOcean workspace has been provisioned in this environment.
No authorized cloud account was provided, and creating billable infrastructure requires
explicit user approval.

Current boundaries:

- Real provider mode has not been exercised against a DigitalOcean project.
- The local web console uses a safe simulated shell when the API/Coder terminal bridge is absent.
- The Coder adapter and Temporal worker contract are represented by deployment templates
  and domain boundaries; production lifecycle calls still require final API wiring and
  failure-injection tests against a supported Coder deployment.
- DigitalOcean Droplet and action IDs are persisted, but asynchronous action polling,
  ambiguous-timeout tag reconciliation, and bootstrap completion belong in the unwired
  Temporal worker and therefore block real-provider mode.
- Browser IDE routing is shown in the Coder template but requires a wildcard Coder access
  domain and OpenVSCode Server installation in the production image.
- Keycloak configuration is a local bootstrap realm, not a production identity policy.
- PostgreSQL RLS deployment policies, KMS integration, distributed rate limiting, idle
  shutdown, and actual-provider billing reconciliation remain operational follow-up work.
- Codex is installed from a pinned package, but a production coding-agent supervisor and
  structured app-server event bridge are not yet connected to the UI.
- Codex app-server support wording is currently inconsistent across OpenAI documentation.
  The stdio adapter is version-pinned and structured, but must be compatibility-tested
  against generated schemas before production use.
- VS Code and Cursor local access require Coder-compatible client/extension setup; it is
  intentionally presented as guided setup, not zero-configuration support.

The mock mode validates UI flow, state transitions, idempotency, cost re-approval, and
application-level tenant isolation without creating chargeable resources.
