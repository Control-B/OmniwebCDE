# Omniweb Cloud Development Environments

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
- `backend/` — FastAPI control plane, tenant-scoped models, provider adapter, state machine, and tests
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

Open <http://localhost:43210>. The frontend uses representative local data if the API is
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
a seeded local organization, and mocked DigitalOcean/Coder operations.

### Full local control plane

```bash
docker compose up --build
```

The reverse proxy listens on <http://localhost:8088>. PostgreSQL, Redis, Temporal,
Keycloak, Coder, the API, and the web app are included. Local passwords are development
defaults and must be replaced outside an isolated workstation.

## Safety

- `OMNIWEB_MOCK_INFRASTRUCTURE=true` is the default.
- Provider tokens are accepted only by the API, encrypted before storage, and never returned.
- Real infrastructure mode is intentionally not enabled by the sample Compose environment.
- Cost figures are estimates. DigitalOcean billing is authoritative, and stopped resources
  can continue to incur storage or other charges.

See [Deployment](docs/deployment.md), [Operations](docs/runbook.md), and
[Known limitations](docs/known-limitations.md) before using a real cloud account.
