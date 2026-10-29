# Omniweb

Omniweb is an AI application builder and a cloud development environment platform. Describe
an application and Omniweb generates real source code, checks it in a sandbox, previews it,
lets you change it by chat, by hand, or by clicking the preview, syncs it to GitHub, and
deploys it to DigitalOcean after you approve the cost. See the
[architecture plan](docs/platform-plan.md) for service boundaries and milestone status.

## Unified business and marketing intelligence

- `/create` is the primary prompt surface for combined software, business planning,
  marketing, text, image, and video requests. AUTO detects multiple intents and creates a
  dependency-aware LangGraph execution; explicit BUILD, BUSINESS, MARKETING, CONTENT,
  IMAGE, VIDEO, and ENGINEERING modes remain available.
- `/projects/<id>/growth` keeps plans, campaigns, funnels, blog/content work, CRM leads,
  analytics, automations, and capability improvements in the same project context as the
  application builder.
- Business plans distinguish sourced claims from assumptions and projections. Marketing
  analytics report only recorded events. Publication, paid actions, media generation, and
  software releases are explicit approval gates.
- The capability-evolution service links authorized evidence to hypotheses, catalog
  matches, implementation runs, tests, releases, marketing proposals, and measured
  outcomes in both directions. Correlation is never labelled causation.

The detailed inventory, patent-source gap, traceability matrix, contracts, relational
migration plan, security boundaries, cost policy, and architecture decisions are in
[`docs/unified-intelligence-architecture.md`](docs/unified-intelligence-architecture.md).
No patent draft or technical drawings were present in this repository, so the
traceability report maps only the mechanisms supplied as product requirements and makes
no patent-coverage claim.

## Engineering Design Agent

`/projects/<id>/engineering` is the integrated parametric mechanical-design workspace.
It extracts editable requirements, generates genuine CadQuery/OpenCascade STEP and STL
geometry, creates PDF and DXF drawings, displays an interactive Three.js preview, runs
Level 1 geometry validation, and preserves immutable revisions and review decisions. The
workspace also creates multi-part STEP assemblies with BOMs and interference evidence,
transparent manufacturing cost estimates, and deterministic static, thermal, and modal
screening calculations.
Supported MVP components are plates, equal-leg L brackets, cylindrical spacers, and
open-top enclosures. See
[`docs/engineering-design-agent.md`](docs/engineering-design-agent.md) for service
boundaries, API contracts, isolation, tests, and limitations.

Geometry validation is not structural analysis, code compliance, engineering
certification, or approval for manufacturing.

## Application builder

- `/` — landing page. The prompt has two modes: **Website** (the local website builder
  below) and **Full-stack app**, which creates an application project and starts a build.
- `/projects` — project dashboard: stack, build and deployment status, GitHub repository,
  last modified, and AI cost.
- `/projects/<id>` — the Studio. The left panel holds chat, build progress, the
  specification, Git checkpoints with diffs and undo/redo, and usage. The centre is the
  live preview (desktop, tablet, phone; web and Expo surfaces) with element selection for
  visual edits and an approval banner. The right panel holds a Monaco code editor, the
  database schema and migrations, API routes, environment variables, GitHub sync and
  deploys, and build logs. On phones the Studio shows one pane at a time.
- `/projects/<id>/settings` — application details, model preferences, budget,
  environment variables, collaborators, deletion.
- `/usage` — organization AI spend, budgets, provider keys, routing tiers, model registry.

### What a build produces

Each project is a Git repository (`<OMNIWEB_BUILDER_DATA_DIR>/projects/<id>/repo`) rendered
from a versioned template and the app specification:

- `apps/web` — React, Vite, Tailwind, React Router-style hash routes, Vitest tests.
- `services/api` — FastAPI, SQLAlchemy, Alembic migrations, scrypt password auth, pytest.
- `apps/mobile` — Expo / React Native, previewed through react-native-web.
- `infra/`, `.do/app.yaml`, `.github/workflows` — deployment and CI files.

A build runs the LangGraph pipeline *understand → plan → apply → verify → repair →
finalize*. Every check (type-check, unit tests, web build, API tests, migrations, mobile
bundle) runs in the sandbox with no network, a cleared environment, and resource limits.
The preview only moves to a commit whose checks all passed; until then it keeps showing the
last working version.

### Safety rules the builder enforces

- Data-deleting migrations (dropping a field or model) stop and wait for approval.
- Files you edit by hand are recorded and never overwritten by later generations.
- Every deploy and rollback needs an approval; production also needs the owner to type the
  project name. Agents cannot approve their own requests.
- Previews are served from a separate origin per project (`<token>.preview.localhost`)
  with a strict CSP, so a generated app can't read Omniweb's or another project's storage.
- GitHub sync never force-pushes, refuses to push when GitHub has newer commits, and stops
  on merge conflicts with the list of files. Tokens are short-lived GitHub App
  installation tokens passed through the environment, never written to the repository.

Without AI provider keys, the architect and editor agents fall back to a deterministic
planner that understands common requests ("add a due date to tasks", "remove the notes
field from clients", "add invoices", "make it green", "add sign-in", "add a mobile app").
Automatic repair of failing checks needs a provider.

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
- `services/engineering/` — isolated deterministic parametric CAD, drawing, export, and geometry validation
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

The first build installs the generated apps' shared npm and Python toolchain into
`<OMNIWEB_BUILDER_DATA_DIR>/toolchain`, which needs network access once and takes a minute.
Builds need Node 20+, git, and util-linux `unshare` with unprivileged user namespaces.

### Preview server

```bash
cd backend
uvicorn app.preview_server:app --host 127.0.0.1 --port 43230
```

It serves each project's last verified build and proxies `/api` to that project's
preview API over a Unix socket. Browsers resolve `*.localhost` to loopback, so per-project
origins work locally without DNS. Elsewhere, point a wildcard DNS record at it and set
`OMNIWEB_PREVIEW_URL`.

### Builder settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `OMNIWEB_BUILDER_DATA_DIR` | `./.omniweb` | Project repositories, builds, previews, local GitHub stand-in |
| `OMNIWEB_BUILDER_TOOLCHAIN_DIR` | `<data>/toolchain` | Shared npm and Python packages for generated apps |
| `OMNIWEB_SANDBOX_MODE` | `namespace` | `namespace` (unshare), `container` (Docker/Podman, recommended for production), or `disabled` |
| `OMNIWEB_SANDBOX_TIMEOUT_SECONDS` | `300` | Per-check time limit |
| `OMNIWEB_PREVIEW_URL` | `http://localhost:43230` | Public base URL of the preview server |
| `OMNIWEB_PREVIEW_SUBDOMAINS` | `true` | One origin per project; `false` falls back to `/p/<token>/` paths |
| `OMNIWEB_MAX_REPAIR_ATTEMPTS` | `2` | Repair passes before a build is marked as needing attention |
| `OMNIWEB_GITHUB_APP_ID`, `OMNIWEB_GITHUB_APP_PRIVATE_KEY` | empty | Sync with github.com through a GitHub App. Empty uses a local bare repository |
| `OMNIWEB_MOCK_INFRASTRUCTURE` | `true` | Deploys go to a mock App Platform; set `false` only with an authorized DigitalOcean token |

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

### Adaptive AI Execution Engine

```bash
cd services/ai-execution-engine
python3 -m pip install -e '.[dev]'
python3 -m uvicorn aaee.main:app --reload --port 8030
```

The backend calls AAEE at `OMNIWEB_AAEE_URL` and signs requests with
`OMNIWEB_AAEE_SECRET`; AAEE uses `AAEE_SERVICE_SECRET` to verify them. AAEE is the single
cost-aware router for builder, business, marketing, and content tasks. It uses
deterministic tools first, then configured GPT-OSS/Grok/OpenAI routes by task phase and
bounded escalation. Codex is intentionally not a provider. Model estimates and configured
budget ceilings are controls, not guarantees of provider billing.

### Engineering CAD service

```bash
cd services/engineering
python3 -m pip install -e '.[dev]'
python3 -m uvicorn engineering.main:app --reload --port 8040
```

The backend calls this service at `OMNIWEB_ENGINEERING_SERVICE_URL`. The service accepts
validated declarative specifications only and does not execute user- or LLM-authored
Python. `docker compose up --build` runs it as a non-root, read-only, resource-limited
service without external network access.

### Media providers

Media adapters are disabled until an administrator configures credentials, verifies model
access and pricing, and authorizes a job. No paid generation is performed by setup or
tests.

| Variable | Purpose |
| --- | --- |
| `OMNIWEB_OPENAI_MEDIA_API_KEY` | Server-only OpenAI media credential |
| `OMNIWEB_OPENAI_IMAGE_MODELS` | Admin-allowed image models |
| `OMNIWEB_OPENAI_VIDEO_MODELS` | Admin-allowed video models; empty means unavailable |
| `OMNIWEB_MEDIA_PRICING_JSON` | Operator-validated estimates used before authorization |
| `OMNIWEB_ASSET_DATA_DIR` | Object-store adapter data directory |

At implementation time the official OpenAI schema exposed GPT Image 1/1.5-family image
models and a Sora 2 video endpoint. The requested names `gpt-image-2.5-flare` and
`gpt-image-2.5-sunburst` could not be verified and are not registered. Video capability
remains unavailable unless a configured account is explicitly validated; unsupported
features fail with a capability status rather than a false promise.

### Tests

```bash
(cd backend && pytest && ruff check .)
(cd services/model-gateway && pytest && ruff check .)
(cd services/ai-execution-engine && pytest && ruff check .)
(cd frontend && npm run typecheck && npm run build)
# Browser tests run against the dev servers above:
(cd frontend && npx playwright install chromium && npm run test:e2e)
```

### Full local control plane

```bash
docker compose up --build
```

The reverse proxy listens on <http://localhost:8088>. PostgreSQL, Redis, Temporal,
Keycloak, Coder, the model gateway, the API, the preview server (port 43230), and the web
app are included. The Compose stack has not been run in this repository's development
environment, which has no container runtime. To sign in
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
