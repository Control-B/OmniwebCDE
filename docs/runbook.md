# Operations runbook

## Provisioning is stuck

1. Locate the workspace and Temporal workflow by workspace UUID.
2. Compare Omniweb state with Coder workspace/build state and the DigitalOcean resource ID.
3. Do not retry Droplet creation until the provider inventory confirms no matching
   `workspace-<uuid>` tag exists.
4. Resume the workflow from the last idempotent activity or move it to `RECOVERING`.
5. If cleanup fails, mark the workspace `FAILED`, display the provider resource ID, and
   alert an operator that billing may continue.

## Agent cannot connect

Check outbound DNS/HTTPS, Coder access URL, workspace-agent logs, clock synchronization,
and expiry of the workspace-scoped bootstrap credential. Never open public SSH as a
workaround. Rebuild only after confirming persistent volume policy with the user.

## Provider rate limiting or outage

Honor `Retry-After`, apply bounded exponential backoff in Temporal, and keep the same
idempotency key. Pause reconciler fan-out if provider-wide failures occur.

## Credential incident

1. Disable the cloud connection and revoke the provider token at DigitalOcean.
2. Revoke affected Coder sessions.
3. Rotate the envelope-encryption key through a staged re-encryption job.
4. Search audit metadata, not terminal content, for affected operations.
5. Notify impacted tenant owners according to the incident policy.

## Orphan reconciliation

Periodically compare provider resources tagged `omniweb` with non-deleted workspaces.
Quarantine unmatched resources, record an audit event, and require explicit operator
approval before deletion. Report all potentially billable leftovers to the tenant.

## Backup and recovery

Back up PostgreSQL and infrastructure state with encryption and tested restore procedures.
Workspace volumes follow the customer's selected backup policy. Redis is not authoritative.
Temporal persistence and Coder's database are required for workflow/runtime recovery.
