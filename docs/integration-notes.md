# Verified integration notes

Checked against vendor documentation on 2026-10-27.

## Coder

The adapter uses Coder's documented v2 API:

- create: `POST /api/v2/organizations/{organization}/members/{user}/workspaces`
- status: `GET /api/v2/workspaces/{workspace}`
- lifecycle: `POST /api/v2/workspaces/{workspace}/builds` with `start`, `stop`, or `delete`
- observation: workspace watch SSE/WebSocket and agent lifecycle/health fields

The service token remains server-side. Browser IDE access comes from an owner-only
`coder_app`; launch URLs are constructed from Coder's public access URL rather than
returning the app's internal workspace target. Terminal streams must be proxied to Coder's
workspace-agent PTY API using a user-scoped session rather than exposing the Omniweb
service token. Subdomain apps are preferred because path apps share the dashboard origin.

Coder organizations are the practical tenant boundary, but multi-organization support and
several SaaS controls require Premium licensing. Production must either map each Omniweb
tenant to a licensed Coder organization or deploy isolated Coder control planes. Disable
implicit deployment-owner workspace access where the selected Coder edition supports it.

Sources: [Coder workspace API](https://coder.com/docs/reference/api/workspaces),
[Coder builds API](https://coder.com/docs/reference/api/builds), and
[Coder agent API](https://coder.com/docs/reference/api/agents).

## DigitalOcean

The provider adapter validates `/v2/account` status, email verification, and basic Droplet
quota; reads `/v2/regions` and `/v2/sizes`; uses `price_monthly` only as an estimate; and
creates/deletes Droplets through `/v2/droplets`. It records both the returned Droplet ID and
asynchronous action ID. A `202` response is not readiness, and cloud-init completion is a
separate signal. Omniweb supplies its own idempotency and resource-tag reconciliation
because create has no documented idempotency-key contract. DigitalOcean account passwords
are never requested.

Powering off a Droplet does not stop billing. API list results are paginated and catalog
availability is not a capacity reservation. Production reconciliation must honor
`Retry-After`, inspect action completion, and distinguish authentication, quota, capacity,
and bootstrap failures.

## Codex

Codex integration uses `codex app-server`, not terminal scraping. The adapter speaks the
documented newline-delimited JSON-RPC protocol over stdio:

- `initialize` / `initialized`
- `model/list` before presenting or accepting model IDs
- `thread/start`, `turn/start`, `thread/read`, and `turn/interrupt`
- streamed item and turn notifications
- server-initiated command/file approval requests with explicit decisions

No arbitrary routing, monetary cap, or token-budget control is assumed. The model selector
must reflect the live `model/list` catalog and its supported reasoning efforts; catalog
presence does not prove account entitlement. Pin Codex and generate schemas from that exact
binary. Current documentation is inconsistent about app-server production support, so
stdio is treated as the least ambiguous transport and must pass compatibility tests before
production rollout.

Source: [Codex app-server](https://developers.openai.com/codex/app-server).
