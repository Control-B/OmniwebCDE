# Security model

- OIDC access tokens are validated for signature, issuer, audience, expiry, and tenant claims.
- Development identity fallback is disabled when `OMNIWEB_ENVIRONMENT=production`.
- Every resource query includes the authenticated organization ID; cross-tenant misses return 404.
- Provider tokens are encrypted at rest and omitted from response schemas, logs, cloud-init,
  browser state, and workspace environments.
- Workspace access tokens expire after five minutes and bind user, tenant, workspace, mode,
  and nonce. WebSockets validate origin and ownership before accepting.
- The DigitalOcean firewall has no inbound rules. Workspace agents connect outbound.
- Workspace users are non-root. Password and root SSH login are disabled.
- Resource creation requires an approved cost that exactly matches the current catalog.
- Lifecycle transitions are allow-listed and recorded as immutable events.

Production must use KMS-managed envelope encryption, restricted service identities, RLS,
distributed rate limiting, CSRF-safe OIDC cookies or bearer headers, and a dedicated access
service that bridges only to Coder's supported terminal endpoint.

Security automation targets are defined in `.github/workflows/security.yml`. Scanners run
against source and images; OWASP ZAP is limited to the non-destructive baseline profile.
