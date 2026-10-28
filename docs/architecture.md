# Architecture decision record: DigitalOcean vertical slice

Status: accepted for MVP

## Decision

Use Omniweb as a tenant-aware control plane and Coder as the authoritative workspace
runtime. The browser talks only to Omniweb. Omniweb validates organization membership,
cost approval, and lifecycle policy before calling Coder or DigitalOcean.

The initial deployment is a modular monolith with independently extractable domains:

1. Identity and policy — OIDC, organization membership, roles, audit events.
2. Cloud connections — encrypted provider credentials and catalog validation.
3. Workspace — user-facing state projection, quotas, cost approval, idempotency.
4. Provisioning — Temporal workflows and provider/Coder adapters.
5. Access — short-lived workspace-scoped links and WebSocket authorization.
6. Coding agents — provider-neutral session and approval contract.

Keeping these boundaries in one FastAPI deployment reduces distributed failure modes in
the first vertical slice. Domains communicate through service interfaces and API contracts;
they do not become independent network services until scaling or ownership requires it.

## Workspace state

Omniweb records every validated transition:

`REQUESTED → VALIDATING → PROVISIONING → BOOTSTRAPPING → CONNECTING → READY`

Lifecycle and recovery states are `STOPPING`, `STOPPED`, `STARTING`, `REBUILDING`,
`DELETING`, `DELETED`, `FAILED`, and `RECOVERING`. Coder remains authoritative for
runtime truth. A reconciler projects Coder/provider observations into Omniweb state.

## Trust boundaries

- Browser: untrusted. Organization IDs from requests are ignored.
- Control plane: trusted for policy; provider secrets are envelope-encrypted.
- Coder: trusted runtime service, isolated from browser admin credentials.
- Workspace VM: executes arbitrary customer code and cannot access provider credentials.
- Provider: authoritative for resources, quota, and billing.

Browser access uses short-lived links scoped to user, organization, workspace, and access
mode. Production WebSockets require a matching origin and re-check workspace ownership.

## Browser IDE choice

Use Coder's application proxy with OpenVSCode Server/code-server rather than rebuilding
VS Code. The Coder template defines an owner-only app and agent transport. This preserves
extension, language-server, Git, terminal, and debugger support while keeping the VM
address private.

## Persistence and billing

Project files live on a separately managed DigitalOcean volume mounted at `/workspace`.
Stop/start preserves that volume. Rebuild policy must explicitly preserve or replace it.
Deleting the workspace removes compute and then verifies attached resources. A stopped
Droplet or retained volume may continue billing; Omniweb never labels estimates as invoices.

## Alternatives rejected

- Custom SSH tunnels: duplicates Coder's authenticated agent transport.
- Home-grown password identity: increases credential and recovery risk.
- One service per domain at MVP: adds network and operational failure modes without scale evidence.
- Kubernetes, Kafka, and a service mesh: no demonstrated MVP requirement.
