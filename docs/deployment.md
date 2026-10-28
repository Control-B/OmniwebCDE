# Deployment guide

## Required production services

- PostgreSQL with encrypted backups and separate databases for Omniweb, Coder, and Temporal
- Redis with authentication and private networking
- Temporal with durable persistence
- A supported Coder deployment and isolated provisioner
- OIDC provider such as Keycloak, Auth0, or Okta
- HTTPS ingress with a workspace wildcard domain for Coder applications
- A KMS-backed secret encryption key

## Required configuration

Set at minimum:

```text
OMNIWEB_ENVIRONMENT=production
OMNIWEB_DATABASE_URL=postgresql+asyncpg://...
OMNIWEB_FRONTEND_ORIGIN=https://app.example.com
OMNIWEB_OIDC_ISSUER=https://identity.example.com/realms/omniweb
OMNIWEB_OIDC_AUDIENCE=omniweb-api
OMNIWEB_ENCRYPTION_KEY=<Fernet key from a secret manager>
OMNIWEB_CODER_BASE_URL=https://coder.internal.example.com
OMNIWEB_CODER_TOKEN=<restricted service account token>
OMNIWEB_MOCK_INFRASTRUCTURE=false
```

Do not use Compose defaults in production. Restrict the Coder API token to the operations
required by the adapter, and keep DigitalOcean credentials in Omniweb's encrypted control
plane storage. Provider tokens must never be injected into a workspace.

## Database

Run Alembic migrations before replacing API instances:

```bash
cd backend
alembic upgrade head
```

Apply PostgreSQL Row-Level Security policies after creating the runtime role. The API
must set the authenticated organization ID for each transaction. Application predicates
remain mandatory; RLS is defense in depth.

## Coder template

Upload `infrastructure/coder/digitalocean` using the supported Coder CLI or API. Configure
the DigitalOcean provider credential on the isolated provisioner, not as a template
parameter. Confirm the generated plan creates no inbound firewall rule and that the agent
can reach Coder over outbound HTTPS.

## Release checks

1. Run backend tests and Ruff.
2. Run frontend type checking, build, and dependency audit.
3. Scan images with Trivy and source with Semgrep/Gitleaks.
4. Apply migrations.
5. Deploy the API and worker, then the frontend.
6. Execute the tenant-isolation and idempotency smoke tests.
7. Provision only in a designated test project after a human approves the displayed cost.
