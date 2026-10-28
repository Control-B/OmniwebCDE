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
- VS Code and Cursor local access require Coder-compatible client/extension setup; it is
  intentionally presented as guided setup, not zero-configuration support.

The mock mode validates UI flow, state transitions, idempotency, cost re-approval, and
application-level tenant isolation without creating chargeable resources.

## Application builder

- AI agents (architect, editor, repair) have only been exercised through their fallback
  paths because no provider keys were available. Without a provider, edits are limited to
  the patterns the built-in planner understands, and failing checks are not repaired
  automatically.
- GitHub sync has been tested against a local bare repository only. Real GitHub App
  installation tokens, branch protection, and webhooks are untested.
- App Platform deploys and rollbacks have run only against the mock provider. No
  DigitalOcean resources were created.
- The namespace sandbox isolates network, filesystem, processes, and environment, and caps
  CPU time, file size, and process count with `prlimit`. It has no memory cgroup limit.
  The `container` sandbox mode is implemented but untested, so use it only after testing
  it on a dedicated build host.
- Preview APIs use SQLite, while deployed apps use managed PostgreSQL. The generated code
  targets both through SQLAlchemy, but PostgreSQL migrations are only exercised on deploy.
- The Expo app is bundled for the web preview but not type-checked, and native builds,
  signing, and store submission are out of scope.
