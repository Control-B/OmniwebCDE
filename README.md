# Omniweb

Omniweb is an AI application builder and a cloud development environment platform. Describe
an application, plan it with a requirements assistant, and (from Milestone 2) have Omniweb
generate, preview, and deploy it to infrastructure you own. See the
[architecture plan](docs/platform-plan.md) for service boundaries and the milestone roadmap.

## Application builder (Milestone 1)

- `/` — landing page. The prompt has two modes: **Website** (the local website builder
  below) and **Full-stack app**, which creates an application project.
- `/projects` — project dashboard: name, description, stack, generation and deployment
  status, GitHub repository, last modified, and AI usage cost.
- `/projects/<id>` — three-panel builder. The left panel holds chat, agent progress,
  requirements, file changes, and project usage. The centre holds the preview with
  device sizes and full screen. The right panel holds files, database, API, environment
  variables, deployment, and logs. Side panels resize and hide; on phones the builder
  shows one pane at a time.
- `/projects/<id>/settings` — application details, model tier preferences, budget,
  environment variables, credentials, GitHub, deployment targets, collaborators, deletion.
- `/usage` — organization AI spend, budget, billing models, provider keys, routing tiers,
  and the discovered model registry.

Code generation is not part of Milestone 1. The builder gathers requirements through the
model gateway, and the preview says so plainly.

### Model gateway

`services/model-gateway` is a separate FastAPI service. It is the only component that
holds provider keys. The control plane calls it with short-lived signed service tokens,
and browsers never reach it. It supports OpenAI, Anthropic, Gemini, OpenRouter,
OpenAI-compatible endpoints, and Ollama. Model IDs come from each provider's list-models
API, never a hardcoded list. The gateway also handles routing tiers with bounded fallback,
per-task, per-project and monthly budgets with hard limits, a usage ledger, and
cancellation.

Without any provider key, chat replies come from a clearly labelled **development model**
that makes no AI calls and costs $0. To use a real model, an organization admin adds a key
under **Usage → Providers**, or the operator sets `GATEWAY_OPENAI_API_KEY` (or the
Anthropic, Gemini, or OpenRouter equivalent) for platform-managed billing.

## Cloud development environments

Omniweb CDE is a multi-tenant control plane for creating secure remote development
workspaces in a customer's DigitalOcean account. Users choose infrastructure, approve
its estimated cost, and open the same workspace in a browser IDE or web console without
managing SSH keys or public VM addresses.

This repository contains a functional local vertical slice. Infrastructure operations
run in safe mock mode by default; no billable resource is created without changing the
configuration and providing an authorized, scoped DigitalOcean token.

## Website builder

The landing page at `/` is a prompt-to-website builder. Describe a site, and Omniweb
generates a responsive, single-file website shown in a live preview at
`/build/<projectId>`. Refine it by chatting ("make it dark", "add an FAQ", `headline
"Ship faster together"`, "rename it to Atlas", "make it a restaurant"). Every change is
a version you can undo or redo. The builder can switch between desktop, tablet, and
mobile previews, show the generated HTML, copy it, open it in a new tab, or export it.

The designer engine (`frontend/src/lib/site-generator.ts`) runs entirely in the browser
and needs no API keys. Projects are saved in the browser's local storage. The cloud
workspaces dashboard is unchanged and now lives at `/app`.

## Repository layout

- `frontend/` — TanStack Start dashboard, provisioning wizard, workspace details, and xterm console
- `backend/` — FastAPI control plane: identity, projects, workspaces, provider adapter, and tests
- `services/model-gateway/` — model discovery, registry, routing, budgets, and usage ledger
- `assets/` — product images and marks
- `infrastructure/` — Coder template, cloud-init, Caddy, identity, and container configuration
- `docs/` — architecture, deployment, operations, API, security, and known limitations

## Quick start

### Web experience

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:43210> for the builder, or <http://localhost:43210/app> for cloud
workspaces. The frontend uses representative local data if the API is
not running, so the full dashboard and console can be evaluated immediately.

### API

```bash
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8010
```

OpenAPI is available at <http://localhost:8010/docs>. Development mode uses SQLite,
a seeded local organization, and mocked DigitalOcean/Coder operations. Without
`OMNIWEB_OIDC_ISSUER`, requests use a local development identity, which the UI labels.

### Model gateway

```bash
cd services/model-gateway
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn gateway.main:app --reload --port 8020
```

The control plane expects it at `http://127.0.0.1:8020` (`OMNIWEB_MODEL_GATEWAY_URL`).
Both services share the development secret by default; set `OMNIWEB_MODEL_GATEWAY_SECRET`
and `GATEWAY_SERVICE_SECRET` to the same value outside development.

### Tests

```bash
(cd backend && pytest && ruff check .)
(cd services/model-gateway && pytest && ruff check .)
(cd frontend && npm run typecheck && npm run build)
# Browser tests run against the dev servers above:
(cd frontend && npx playwright install chromium && npm run test:e2e)
```

### Full local control plane

```bash
docker compose up --build
```

The reverse proxy listens on <http://localhost:8088>. PostgreSQL, Redis, Temporal,
Keycloak, Coder, the model gateway, the API, and the web app are included. To sign in
through Keycloak instead of the development identity, set
`OMNIWEB_OIDC_ISSUER=http://localhost:8180/realms/omniweb` before building. The
`model_gateway` database is created on first start of a fresh PostgreSQL volume. Local passwords are development
defaults and must be replaced outside an isolated workstation.

## Safety

- `OMNIWEB_MOCK_INFRASTRUCTURE=true` is the default.
- Provider tokens are accepted only by the API, encrypted before storage, and never returned.
- Real infrastructure mode is intentionally not enabled by the sample Compose environment.
- Cost figures are estimates. DigitalOcean billing is authoritative, and stopped resources
  can continue to incur storage or other charges.

See [Deployment](docs/deployment.md), [Operations](docs/runbook.md), and
[Known limitations](docs/known-limitations.md) before using a real cloud account.
