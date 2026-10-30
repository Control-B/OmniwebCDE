# Omniweb operating policy 1.0

The Master Agentic System Instructions are implemented in
`backend/app/intelligence/policy.py` and applied to every Unified Create workflow. This page
records which parts application code enforces and which parts are model guidance.

Model instructions are guidance, not a security boundary. Authentication, tenant and project
authorization, approvals, budgets, sandboxing and execution limits stay enforced in the API,
the adaptive AI execution engine (AAEE), the model gateway and the isolated workers.

## What runs on every workflow

| Policy section | Implementation |
|---|---|
| Instruction hierarchy (2) | Seven-level hierarchy prefixed to every model system prompt. The user request is sent inside an `<untrusted_data>` block; embedded closing delimiters are stripped. |
| Task understanding (3) | Deterministic intent detection, domain classification (software, marketing, engineering) and a recorded risk assessment. |
| Agent handoffs (3) | Each task stores a handoff with task ID, organization, project, authorized capabilities, output schema, acceptance criteria, token budget, risk and approval requirements. |
| Domain instructions (4–6) | Software, marketing and engineering rules are composed into the specialist's system prompt. |
| Safety-critical and regulated work (5.8, 6.9) | Structural, pressure, medical, aerospace, automotive, electrical, hazardous, financial, health-claim and minors keywords raise risk to high and add a qualified-review requirement. Engineering review notes include it. |
| Sensitive data (7) | Personal, health and payment data keywords raise risk and require confirmation of lawful basis, consent and retention. |
| Prompt injection (7) | Override phrases are counted, raise risk to high and are recorded; the request still runs under unchanged controls. |
| Cost limits (9) | Per-kind output-token budgets are sent to AAEE, which enforces reservations and budgets. |
| Human approval (13) | Deployment, publication, advertising spend, paid media, customer messaging, engineering release and destructive data operations are classified high risk and listed as required approvals. The existing endpoints enforce those gates. |
| Quality record (14) | Every completed task stores a record with status, method, verification evidence, limitations, outstanding approvals, professional review and next actions. |

`GET /api/v1/intelligence/policy` returns the version, hierarchy, domains, statuses and
high-risk actions. Workflow responses include `assessment`, each task's `handoff`, and
`output.quality_record`.

## Completion statuses

`proposed → generated → tested → verified → approved → deployed`

A quality record reports only what recorded evidence supports. Unified Create tasks report
`proposed` or `generated`: builder verification, CAD validation, publication and deployment
happen later in their own workflows, each with their own evidence and approval records.
Media jobs and engineering designs that are missing critical requirements report `proposed`.

## Limits

- Risk and regulated-category detection uses keyword rules. It is a conservative trigger
  for review, not a legal, regulatory or engineering determination.
- The jurisdiction question for marketing is raised but not yet blocking.
- Compliance source records (section 8) and the full bidirectional improvement workflow
  (section 10) use the existing capability evolution service; this policy layer doesn't
  add new legal rule data.
- No part of this layer certifies legal compliance, engineering safety or manufacturing
  approval.
