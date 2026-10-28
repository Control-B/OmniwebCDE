# Security verification results

Run on 2026-10-27 against the committed local vertical slice.

| Check | Result |
| --- | --- |
| Semgrep OWASP Top Ten rules | Passed; 224 rules, 29 files, 0 findings |
| Gitleaks repository history | Passed; 2 commits, no leaks found |
| npm audit | Passed; 0 known vulnerabilities |
| Ruff security rules | Passed |
| Tenant isolation integration test | Passed; cross-tenant workspace lookup returns 404 |
| Cost re-approval integration test | Passed |
| Idempotent create integration test | Passed |

Trivy image scanning was not run locally because this environment has no Docker daemon.
The pinned CI workflow builds and scans the API image, failing on high or critical issues.
OWASP ZAP was not aimed at any production endpoint; a non-destructive baseline scan should
run against a deployed test environment after OIDC and Coder routing are configured.
