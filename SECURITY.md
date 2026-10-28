# Security policy

Stonebreaker 0.9.0-beta.1 is a prerelease and is not approved for deployment on an untrusted network. Do not send real customer data to an external proposal provider.

## Reporting a vulnerability

Please report security issues privately to the repository maintainers through GitHub's private vulnerability reporting feature. Include the affected version, a reproduction, and potential impact. Do not put credentials, production data, or exploit details in a public issue.

## Current security boundaries

- The API key is a shared service credential, not an end-user identity. Keep it out of browser sessions shared with untrusted users.
- Do not expose the development Docker Compose deployment to the public internet. Configure TLS, firewalling, backups, and secrets handling at the deployment boundary.
- Analytics APIs accept only named reports; they do not execute caller-provided SQL.
- Imported content and column names are untrusted. External AI requests contain profile metadata only; review all proposals before use.
- There is no claim of a completed penetration test, dependency scan, per-user RBAC, rate limiting, or security support SLA.
