# ADR 0001: Adaptive AI Execution Engine (AAEE)

Status: accepted · Date: 2026-10-28

## Context

Omniweb has two products that call AI: the full-stack application builder and the cloud
development environment (CDE). Both need to pick the cheapest way to finish a task
*successfully*, which is not the same as the cheapest model per token. A task that a
deterministic template can do should cost nothing. A routine task should go to a low-cost
model such as GPT-OSS or an economical Grok model. Stronger OpenAI or Grok models should
be used only when the development phase, measured quality, or verified failures justify
them.

**Revision (2026-10-28):** Omniweb no longer uses Codex. The Codex strategy, its adapter, and
the Codex CLI in the workspace template were removed. Model choice now follows the project's
development phase, using OpenAI models through the platform's OpenAI API key, plus
low-cost GPT-OSS and Grok (xAI) models.

## 1. Existing implementation inventory

| Concern | Where | State before this ADR |
| --- | --- | --- |
| Provider adapters, LiteLLM | `services/model-gateway/gateway/inference.py`, `providers.py` | Working. OpenAI, Anthropic, Gemini, OpenRouter, OpenAI-compatible, Ollama. Chat Completions only. No xAI provider. |
| Model discovery and registry | `gateway/registry.py`, table `model_registry` | Working. Discovery via each provider's list-models API, pricing from the provider or LiteLLM's cost map, `pricing_source` marks unknown pricing. |
| Per-call usage ledger | gateway table `usage_records` | Working. Tokens, cost, latency, attempt, billing model (platform or customer key). |
| Budgets | gateway `budgets.py` | Organization monthly and project budgets, hard limits and alerts, checked against actual spend. No reservations. |
| Tier routing and fallback | gateway `routing.py` | Price-band tiers with bounded escalation inside one request. |
| Service authentication | `backend/app/services/gateway.py`, `gateway/security.py` | Short-lived HS256 service tokens minted by the control plane. |
| LangGraph orchestration | `backend/app/builder/pipeline.py` | Builder pipeline understand → plan → apply → verify → repair → finalize with durable run state. Calls the gateway directly. |
| Codex integration | `backend/app/coding_agents/codex.py` | A Codex app-server adapter, not wired to any API. Removed in this revision. |
| Coder workspaces | `backend/app/adapters/coder.py`, `services/workspaces.py` | Workspace lifecycle and access tokens, mocked by default. |
| Generation and build pipeline | `backend/app/builder/` | Templates, sandboxed checks (namespace sandbox), previews. |
| Billing and usage UI | `/usage`, `projects_api.py` | Reads gateway usage. |
| Authentication | `backend/app/security.py` | OIDC with a development identity. |
| Durable workflows | Temporal in `docker-compose.yml` | Infrastructure only; no workflows exist in code. |
| Tests | `backend/tests`, `services/model-gateway/tests`, `frontend/e2e` | 20, 15, and 5 tests. |

## 2. Gap analysis

| Requirement | Gap |
| --- | --- |
| Unified task contract | None existed; callers send raw chat messages. |
| Deterministic-first execution | The builder had a deterministic planner but called the model *first* and used the planner only as a fallback. |
| Expected cost per successful task | Routing compared token prices only. |
| Low-cost strategy | GPT-OSS models were reachable through OpenRouter, OpenAI-compatible servers, or Ollama but were not a distinct strategy. Grok was not supported. |
| Phase-aware model choice | Nothing tied model choice to the development phase. |
| Responses API | Not supported by the gateway. |
| Validation evidence and acceptance criteria | The builder ran checks but did not persist evidence against acceptance criteria shared with other callers. |
| Escalation controller | Only in-request tier fallback; no failure classification, duplicate-failure detection, or file leases. |
| Hierarchical budgets with reservations | No platform, user, task, or agent-execution budgets; no reservations, so concurrent tasks could overspend. |
| Performance learning | No outcome statistics, benchmarks, shadow policies, or experiments. |
| Admin dashboard | None. |
| CDE agent tasks | The AI agents page used representative data only. |

## 3. Service boundaries

```
Builder (LangGraph) ─┐                               ┌─ Model gateway ── providers (OpenAI Responses/Chat,
CDE agent tasks ─────┼─► Control plane ─► AAEE ──────┤                    Anthropic, Gemini, OpenRouter,
Future agents ───────┘   (authN, authZ,   (decide,    │                    GPT-OSS endpoints, Ollama)
                          workspaces)      budget,    │                    xAI Grok, GPT-OSS endpoints, Ollama)
                                           account)   └─ Engine tools (gitleaks, text replace, ruff format…)
```

- **Control plane** (`backend`) keeps authentication, workspace authorization, projects,
  the builder pipeline, the build sandbox, previews, deploys, and the CDE. It is the only
  caller of AAEE, and it signs a short-lived service token per request whose tenant, user,
  role, and project come from the authenticated principal.
- **AAEE** (`services/ai-execution-engine`, package `aaee`) is new and separately
  deployable. It owns the task contract, classification, the registry *overlay*, the
  routing policy, planning, escalation, budgets with reservations, the task-level usage
  ledger, validation evidence, performance statistics, benchmarks, and analytics.
- **Model gateway** stays the only holder of provider credentials and the only component
  that calls LLM providers. It remains the source of truth for discovered models, raw
  pricing, the per-call usage ledger, and organization and project budget limits.
  AAEE never receives provider keys.
- **Build workspaces** stay where they are. The builder's sandbox runs builds, tests, and
  previews. For CDE tasks, the control plane applies the returned file edits in the user's
  Coder workspace and runs the checks there. AAEE never executes generated code.

### Not duplicated

- **Discovery.** AAEE reads the gateway registry and stores only an overlay: enablement,
  priority, admin-validated pricing, infrastructure cost, rate limits, and capability
  overrides.
- **Per-call ledger.** Every LLM call still lands in the gateway's `usage_records`, now with
  `task_id` and `execution_id`. AAEE's ledger records attempts, strategies, validation, and
  non-gateway costs (tools).
- **Organization and project limits.** These live in the gateway. AAEE reads limit and
  spend from it, then adds reservations on top. Platform, user, task, and agent-execution
  budgets are new and live in AAEE.
- **Orchestration.** The builder keeps its LangGraph graph and calls AAEE from its nodes.
  AAEE does not run a second agent graph.

## 4. Integration architecture

### Execution protocol

1. The caller sends `POST /v1/tasks` with a `TaskRequest`. Tenant, role, and project come
   from the token. Risk level, approval requirements, and authorization claims are always
   computed by the server, and requests that try to supply them are rejected.
2. AAEE classifies the task with deterministic rules, builds candidates, filters them by
   capability, pricing, security, budget, and latency, and ranks them by expected cost per
   successful task. It returns the next action:
   - `deterministic`: the caller runs a registered tool, such as the builder's spec rules. It costs $0.
   - `result`: AAEE ran an inference strategy through the gateway and returns validated output.
   - `approval_required`: a human must approve before anything runs.
3. The caller runs its checks in its own isolated workspace and submits evidence. AAEE
   evaluates it against the task type's acceptance criteria and persists it. On failure,
   the escalation controller classifies the error and picks a deterministic repair or a
   stronger model, or it stops with a diagnostic report.
4. Usage is reconciled idempotently. Reservations are released on completion, failure, or
   cancellation.

### Durability

Temporal is provisioned but has no workflows in this repository. AAEE persists tasks,
attempts, reservations, and events in its own database and resumes on startup. Attempts
interrupted mid-run are marked `interrupted`, their reservations are released, and the
escalation controller decides whether to retry. The scheduler sits behind an interface, so
a Temporal-backed implementation can replace it without API changes.

### Streaming

`GET /v1/tasks/{id}/events` is a server-sent-event stream backed by the `task_events`
table. It is resumable with `Last-Event-ID`. The control plane proxies it to browsers.

### Development phases and low-cost models

Every task has a development phase: discovery, architecture, scaffolding, implementation,
debugging, testing, security review, or release. The phase defaults from the task type, and
callers may name another. A phase policy sets the ladder levels models may use, the allowed
providers, and preferred registry models. For example, an administrator can pin specific
OpenAI models for architecture and debugging. A requested phase can never go below the
minimum level of the task type's own phase. Preferred models must exist in the live
registry; AAEE never invents model IDs.

The low-cost stage combines the `gpt_oss` and `grok` families, but a model only counts as
low-cost when its blended price is under the policy ceiling. Pricier Grok models are ranked
in the hosted bands by price. Within the stage, GPT-OSS and Grok compete on expected cost per
successful task.

## 5. Database changes

**AAEE** (Alembic `0001_initial`): `tasks`, `executions` (attempts), `usage_events`
(idempotent), `validation_evidence`, `approvals`, `budgets`, `budget_counters`,
`budget_reservations`, `budget_alerts`, `model_policies` (registry overlay),
`routing_policies` (versioned, with `active`, `shadow`, and `experiment` statuses),
`file_leases`, `task_events`, `artifacts`, `feedback`, `benchmark_runs`, `audit_events`.

**Gateway**: `usage_records` gains nullable `task_id`, `execution_id`, and `strategy`.
`/v1/chat` accepts a pinned `model` with no internal fallback, plus attribution fields.
A new `GET /v1/budgets` returns limits and spend without scanning the usage table. Models
whose cost map mode is `responses` are called through the OpenAI Responses API.

**Control plane**: `generation_runs` gains `aaee_task_ids` and a strategy summary. A new
`agent_tasks` table links CDE workspaces to AAEE tasks.

## 6. Implementation plan

| Milestone | Scope |
| --- | --- |
| 1. Shared execution gateway | Service skeleton, task contract, classifier, registry overlay, capability evaluator, routing policy, baseline planner, gateway client, xAI provider, unit tests |
| 2. Low-cost-first generation | Deterministic and low-cost (GPT-OSS, Grok) strategies, template awareness, validation engine and evidence, basic repair, task ledger |
| 3. OpenAI escalation | Responses API in the gateway, escalation controller, retry policies, hierarchical budgets with reservations |
| 4. Phase-aware OpenAI routing | Development-phase policies (levels, providers, preferred models), approvals, file leases, accounting |
| 5. Product integration | Builder and CDE on AAEE, status APIs, streaming events |
| 6. Optimization | Performance evaluator, benchmarks, shadow policies and experiments, analytics, admin dashboard |

## Consequences

- There is one more hop per AI call. The gateway stays the single credential boundary,
  which keeps the security review surface small.
- Cost controls are estimates enforced with reservations, output limits, and timeouts.
  They are **not** provider-enforced billing caps. Provider-side limits, such as OpenAI
  project budgets, should be configured as well.
- Routing quality depends on outcome data. Until a model has the configured minimum number
  of observations for a task type and complexity, AAEE uses conservative configured
  defaults from the active policy version.
