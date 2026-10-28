# Omniweb application builder: audit and architecture plan

Status: Milestone 1 implemented; Milestones 2–8 not started and require approval.

## 1. Repository audit (before Milestone 1)

| Area | What exists | Assessment |
| --- | --- | --- |
| Control plane (`backend/`) | FastAPI, async SQLAlchemy 2, Alembic, tenant-scoped workspaces, encrypted DigitalOcean tokens, audit events, short-lived IDE/console tokens, Prometheus metrics | Solid base. Keep as the identity, tenancy, and project authority. |
| Identity | OIDC bearer validation plus a development identity outside production | Two defects: JWKS URL was hardcoded to `/.well-known/jwks.json` (Keycloak serves `/protocol/openid-connect/certs`), and the bundled realm did not emit the `org_id` or `omniweb-api` audience claims the API requires. Users were never persisted from OIDC. |
| Workspaces | State machine, idempotency, price re-approval, Coder adapter, DigitalOcean adapter (mock by default) | Preserve unchanged. Reused later for preview and deployment sandboxes. |
| Coding agents | Provider-neutral adapter, Codex app-server JSON-RPC adapter | Keep. The builder's agents call models through the new gateway instead. |
| Frontend (`frontend/`) | TanStack Start, Query, xterm.js; landing website builder at `/`, workspaces dashboard at `/app`, IDE and console routes | Preserve. The website builder generates static HTML in the browser and saves to local storage; it is not the app builder. |
| Infrastructure | Compose with PostgreSQL, Redis, Temporal, Keycloak, Coder, Caddy; OpenTofu Coder template; cloud-init | Docker is not available in this agent environment, so Compose is untested here. |
| Tests | 4 control-plane tests | Thin. Milestone 1 adds identity, projects, isolation, and gateway tests. |

Not present: shadcn/ui components, Monaco, Playwright test suite, LangGraph, LiteLLM, GitHub
integration, project/conversation/usage models, any LLM provider wiring.

## 2. Service boundaries

```
Browser ──► Caddy ──► web (TanStack Start)
                 └──► control-plane API (backend/)        identity, orgs, projects,
                         │  signed service token           conversations, settings,
                         ▼                                  workspaces, audit
                      model-gateway (services/model-gateway)  providers, discovery, registry,
                         │                                     routing, budgets, usage ledger
                         ▼
                   LLM providers (OpenAI, Anthropic, Gemini, OpenRouter,
                   OpenAI-compatible, Ollama)

Later milestones:
  builder-orchestrator  LangGraph supervisor + agents, Temporal workflows (M2, M8)
  preview-runner        isolated containers/VMs for untrusted generated code (M2)
  scm-service           GitHub App, checkpoints, sync (M6)
  deploy-service        DigitalOcean deploys, rollback, health (M6)
```

Why the gateway is a separate service now: it is the only component that holds LLM
provider credentials and enforces spend. Isolating it keeps keys out of the control plane's
blast radius and out of anything that executes generated code. The control plane calls it
with a short-lived HS256 service token carrying `org`, `user`, and `project`; the browser
never talks to the gateway and never receives provider keys.

Projects stay in the control plane because they share its tenancy, membership, and audit
tables; splitting them now would duplicate authorization logic.

## 3. Data model added in Milestone 1

Control plane: `projects`, `project_members`, `conversations`, `messages`,
`agent_executions`, `project_env_vars` (values encrypted, write-only), and persisted
`users`/`memberships` resolved from OIDC.

Gateway: `provider_credentials` (encrypted; `platform` or `customer` billing model),
`model_registry`, `usage_records`, `budgets`, `budget_alerts`.

## 4. Model gateway design

- **Providers**: OpenAI, Anthropic, Gemini, OpenRouter, generic OpenAI-compatible, Ollama.
  Inference goes through LiteLLM. Discovery uses each provider's native list-models API.
- **No hardcoded model IDs.** The registry is populated by discovery. Pricing and context
  windows come from the provider (OpenRouter) or LiteLLM's bundled cost map; unknown prices
  are stored as unknown and such models are excluded from budgeted routing.
- **Registry fields**: provider, model id, capabilities, context window, tool calling,
  structured output, input/output price per million tokens, availability, deprecation,
  last verification time.
- **Tiers**: economy, standard, advanced, self-hosted. A tier is a rule (price band,
  capabilities, provider kind), with optional per-organization pinned models.
- **Routing inputs**: task complexity, required capabilities, estimated context, cost,
  user preferences, remaining budget. Escalation moves at most one tier per retry and is
  capped by `max_escalations`; retries are capped by `max_attempts`.
- **Cost controls**: per-task, per-project, and monthly organization budgets; a request is
  rejected before dispatch if its worst-case cost exceeds what remains. Alerts fire at a
  configurable threshold. Usage is recorded for successful and failed requests with input,
  output, and cached tokens, cost, project, agent, and user. Requests can be cancelled.
- **Development provider**: when no credentials exist and mock mode is on, a clearly
  labelled `omniweb-dev` provider returns deterministic text at zero cost so the product
  flow works offline. It is never selected when real models are available or in production.

## 5. Milestone plan

| # | Scope | Main components | Complexity and risk |
| --- | --- | --- | --- |
| 1 | Foundation: audit, boundaries, auth, projects, model gateway, basic builder UI | control plane, new gateway service, frontend routes | Medium. Real LLM calls untested without keys. |
| 2 | First generated app: prompt → requirements → React scaffold from a versioned template → install, build, test → preview | orchestrator service, template registry, preview runner (container sandbox), Monaco | High. Needs a container runtime for untrusted builds; not available in this environment. |
| 3 | Conversational editing: scoped change plans, file diffs, rebuild, Git checkpoints | orchestrator, project file store, git | Medium. |
| 4 | Full-stack: FastAPI + PostgreSQL template, migrations, auth template | templates, preview runner with database sidecar | High. |
| 5 | Visual editing: source-location mapping, AST edits, undo/redo | Babel/TS AST transforms, preview bridge | High. |
| 6 | GitHub App sync and DigitalOcean deploys with approval, rollback | scm-service, deploy-service | High. Billable; requires explicit approval. |
| 7 | Expo mobile template, shared API client, Expo preview | templates, preview runner | Medium-high. No store publication claims. |
| 8 | Specialist agents on LangGraph, recovery, cost-aware escalation | orchestrator | High; AI usage grows here. |

Capability discovery (business observations → recommendations → builder) is an extension
point: the orchestrator will accept a `CapabilitySpec` input in addition to a user prompt.
It is not part of the MVP.

## 6. AI usage expectations

Milestone 1 makes no model calls on its own. Each builder chat message is one gateway
request. From Milestone 2, a generation run is expected to take tens of model calls
(requirements, plan, per-file generation, repair); economy-tier models handle
deterministic-adjacent tasks and advanced models are reserved for architecture and repair.

## 7. Milestone 1 status

Delivered: OIDC fixes (discovery-based JWKS, realm `org_id` and audience mappers, user
persistence), the projects domain, the model gateway, the landing-page app mode, the
project dashboard, the three-panel builder, project settings, and the usage page.

Verified locally: 15 backend tests, 15 gateway tests, Ruff, TypeScript, a production
build, and 5 Playwright browser tests (project creation and chat, panel collapse and full
screen, write-only environment variables, usage page, and the phone layout). Live
discovery against OpenRouter's public catalog returned 464 models.

Not verified:

- Real model calls, because no provider keys are available here. The adapters use LiteLLM
  and are covered with mocks.
- Keycloak and the Compose stack, because no container runtime is available here.
- Request cancellation keeps in-flight state in memory, so it works only with a single
  gateway instance. Milestone 2 moves it to Redis.
- Tier routing uses price bands as a proxy for capability. Per-task capability scores
  arrive with the orchestrator.
- The new pages reuse the existing hand-written design system rather than shadcn/ui.
  Monaco arrives with generated files in Milestone 2.
