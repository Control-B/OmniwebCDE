# Omniweb unified business, marketing and creative intelligence

## Source audit

No provisional patent draft, technical drawing, PDF, DOCX, or PPTX is present in this repository as of 2026-10-28. This document therefore maps only the bidirectional mechanisms stated explicitly in the product requirements. It does not assert that an implementation is patent-covered or invent missing disclosure.

## Existing implementation inventory

| Area | Reusable implementation |
|---|---|
| Application builder | LangGraph specification → plan → render → isolated verify → repair → preview pipeline; checkpoints, approvals, Git sync and deployment gates |
| CDE | Tenant-scoped workspaces, lifecycle state machine, Coder adapter, mocked DigitalOcean, short-lived access links, AAEE file-proposal tasks |
| AAEE | Unified task contract, classifier, model registry overlay, phase-aware cost-per-success planner, GPT-OSS/Grok low-cost stage, OpenAI escalation, reservations, ledger, validation, approvals, analytics and benchmarks |
| Model gateway | Sole text-model credential holder; OpenAI Responses, xAI, provider registry, pinned requests, BYOK accounting and organization/project budgets |
| Identity and governance | OIDC/development principals, tenant memberships, project roles, audit events and backend-enforced approvals |
| Builder frontend | React 19, TanStack Start/Router dependencies, application Studio, project settings, usage, CDE IDE and console |

## Gaps

- No unified multi-intent create graph or persisted task dependencies.
- No business-plan, campaign, funnel, CMS, CRM, email, automation, brand-kit, media-asset or capability-evolution domain model.
- No media provider protocol, asynchronous media jobs, image adapter, video capability discovery, or object-store abstraction.
- No consent-aware first-party marketing events, attribution, experiments, campaign spending authorization or publication workflow.
- No typed capability/evidence graph or versioned bidirectional lifecycle.
- No unified business/marketing/creative project workspace.

## Architecture decisions

1. Extend the existing FastAPI control plane for transactional business domains. PostgreSQL remains the production database; SQLite remains a deterministic development/test option.
2. Model the capability graph with typed relational nodes and edges. A graph database is not justified by current query requirements.
3. Use LangGraph supervisors for dependency-aware workflow orchestration. Persist workflow and node state so restart and audit do not depend on in-memory graph state.
4. Submit every text/reasoning task to AAEE. Do not add a second model router. Deterministic routing and templates run before model calls.
5. Keep the model gateway as the only text-model credential holder. Media credentials stay in server-side provider adapters and never enter browsers, generated apps, CDEs, prompts, or logs.
6. Reuse builder rendering, preview, checks, checkpoints and deployment approval for funnels and landing pages.
7. Store assets through a content-addressed object-store protocol. The local adapter supports development and CI; production may configure an authorized object store.
8. External publication, email send, paid media, advertising spend, destructive migrations, infrastructure changes, and production release require backend-authorized approvals.
9. Codex remains removed. Engineering tasks use configured OpenAI, xAI/Grok or GPT-OSS models through AAEE.

## Service contracts

### Unified create

`POST /api/v1/intelligence/requests` accepts a prompt, mode (`AUTO`, `BUILD`, `BUSINESS`, `MARKETING`, `CONTENT`, `IMAGE`, `VIDEO`), project, attachments and a client idempotency key. It returns a persisted workflow with dependency-aware nodes. Node kinds are executed by the builder, business, marketing, content or media adapters.

### Media provider

Adapters expose `capabilities`, `estimate`, `submit`, `status`, `cancel` and `retrieve`. Unknown model identifiers or pricing are disabled for automatic execution. Jobs are asynchronous and idempotent. The initial OpenAI image adapter is disabled until the configured account and current API catalog verify an accessible image model. Candidate names in requirements are not entered into the automated registry without verification. The OpenAI video adapter reports unavailable until an active supported endpoint and account entitlement are verified.

### Capability evolution

`Observation → Evidence collected → Hypothesis created → Capability matched → Change proposed → Approved → Implemented → Verified → Released → Outcome measured`, with terminal/alternate `Rejected`, `Failed`, `Rolled back`, and `Inconclusive`. Every transition is versioned, actor-attributed, policy-checked and linked to supporting evidence.

## Explicit bidirectional traceability

| Requirement mechanism | Components | Persistence | Verification |
|---|---|---|---|
| Authorized marketing observation creates an engineering hypothesis | Analytics adapter, evolution supervisor | observation, evidence, hypothesis and transition records | consent and source checks; cross-tenant tests |
| Compare reuse, adaptation and synthesis | Capability matcher and catalog | catalog capability/version and proposal alternatives | deterministic match test and trade-off response |
| Approved capability invokes engineering | Evolution service → existing builder/CDE → AAEE | approval, implementation task and builder run links | approval gate, isolated checks and preview |
| Release creates marketing proposals | Release event → marketing supervisor | software version, affected segments, messaging and asset proposals | unreleased capability publication is rejected |
| Measure the original business objective | Experiment and analytics services | experiment variants, metric definitions, observations and outcomes | actual observations only; inconclusive is not success |
| Preserve evidence through failure/rollback | Versioned lifecycle | immutable transitions and evidence links | failed deployment and rollback trace test |

## Migration sequence

1. Shared workflows, tasks, assets and asset versions.
2. Business plans, sections, claims and scenarios.
3. Brand kits, campaigns, funnels, pages, forms and experiments.
4. Blog sites, articles, versions, categories and publication records.
5. CRM contacts, companies, consent, activities and lead attribution.
6. Durable marketing automation definitions, executions and step logs.
7. Marketing events and aggregate metrics.
8. Capability catalog, typed graph edges, observations, evidence, proposals, transitions and outcomes.

## Security boundaries

- Tenant and authorization claims come from authenticated principals or signed service tokens, never request bodies.
- Generated code, copy and media metadata are untrusted. Validate schemas, paths, secrets, content policy and publication state.
- Do not expose provider keys, control-plane secrets, private evidence, workspace credentials or unrestricted Coder credentials.
- Marketing event capture records consent state and rejects unauthorized personally identifiable data.
- Forms use CSRF protections where cookie authenticated, input validation, rate limiting, honeypot support and safe deduplication.
- Email honors consent, unsubscribe and suppression before enqueueing.
- Safe webhooks require allow-listed HTTPS destinations, request signing, idempotency and bounded retries.
- Automated scanners and LLM reviews do not establish legal or regulatory compliance.

## Cost controls

Separate categories are `text_inference`, `software_generation`, `image_generation`, `video_generation`, `advertising`, and `cloud_infrastructure`. Limits may apply at platform, organization, project, campaign, asset, workflow and task scopes. Estimated controls are not provider-enforced billing limits.

No unverified provider pricing is recorded. Administrators must validate model access, current endpoint compatibility and prices before automated media execution. Ordinary CI uses mocked providers and incurs $0 of paid inference/media spend.

## Implementation milestones

1. Audit, contracts and relational foundations.
2. Unified Create, content assets and provider protocols.
3. Business planning and sourced-claim workflow.
4. Marketing supervisor, funnels, CMS, CRM, email and automations.
5. Bidirectional capability evolution.
6. Evidence, experiments, outcome measurement and rollback.
7. Image/video provider adapters and capability gating.
8. Unified frontend, end-to-end tests, observability and deployment readiness.
