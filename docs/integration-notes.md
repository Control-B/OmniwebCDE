# Verified integration notes

Checked against vendor documentation on 2026-10-27.

## Coder

The adapter uses Coder's documented v2 API:

- create: `POST /api/v2/organizations/{organization}/members/{user}/workspaces`
- status: `GET /api/v2/workspaces/{workspace}`
- lifecycle: `POST /api/v2/workspaces/{workspace}/builds` with `start`, `stop`, or `delete`
- observation: workspace watch SSE/WebSocket and agent lifecycle/health fields

The service token remains server-side. Browser IDE access comes from an owner-only
`coder_app`; terminal streams must be proxied to Coder's workspace-agent transport using
a user-scoped session rather than exposing the Omniweb service token.

Sources: [Coder workspace API](https://coder.com/docs/reference/api/workspaces),
[Coder builds API](https://coder.com/docs/reference/api/builds), and
[Coder agent API](https://coder.com/docs/reference/api/agents).

## DigitalOcean

The provider adapter validates the token through `/v2/account`, reads `/v2/regions` and
`/v2/sizes`, uses `price_monthly` only as an estimate, and creates/deletes Droplets through
`/v2/droplets`. Omniweb supplies its own idempotency and resource-tag reconciliation
because create retries must not be assumed safe without checking provider inventory.
DigitalOcean account passwords are never requested.

## Codex

Codex integration uses `codex app-server`, not terminal scraping. The adapter speaks the
documented newline-delimited JSON-RPC protocol over stdio:

- `initialize` / `initialized`
- `model/list` before presenting or accepting model IDs
- `thread/start`, `turn/start`, `thread/read`, and `turn/interrupt`
- streamed item and turn notifications
- server-initiated command/file approval requests with explicit decisions

No arbitrary routing or billing controls are assumed. The model selector must reflect
the live `model/list` catalog and its supported reasoning efforts.

Source: [Codex app-server](https://developers.openai.com/codex/app-server).
