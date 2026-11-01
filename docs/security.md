# Security hardening & deployment checklist

What the application enforces itself, what it expects the deployment to provide, and what is
still open. Dependency scan results are dated; re-run them before every release.

## Enforced by the application

| Area | Control | Where |
|---|---|---|
| Authentication | OIDC SSO (PKCE, signature/issuer/audience/nonce checks) or demo passwords (scrypt); `COPILOT_PASSWORD_LOGIN=false` turns passwords off | `sso.py`, `security.py` |
| Brute force | 5 wrong passwords lock an account for 15 minutes (DB-backed, survives restarts, shared by replicas). Unknown usernames are counted identically and verified against a dummy hash, so neither the response nor its timing reveals whether an account exists. Wrong-password attempts are also limited to 20/min per client address | `security.authenticate`, `api/main.py` |
| Rate limits (per user) | chat 20/min and gap analysis 5/10 min (each call spends LLM quota); every other endpoint 300/min. 429 carries `Retry-After`. Only the first violation per window is written to the audit chain, so an attacker cannot flood it | `ratelimit.py` |
| Authorisation | Role checks in the API; clearance/department filter in the retrieval SQL **and** Postgres row-level security | see architecture.md |
| Session | httpOnly, `SameSite=Lax`, `Secure` in production cookie; token never readable by page scripts; role re-read from the DB on every request | `web/src/app/api/auth/*` |
| Browser | CSP (`default-src 'self'`, no framing, no third-party scripts/connections), `X-Frame-Options: DENY`, `nosniff`, restrictive `Permissions-Policy`, HSTS in production | `web/next.config.ts` |
| API responses | `Cache-Control: no-store`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS in production; optional `COPILOT_ALLOWED_HOSTS` | `api/main.py` |
| CORS | **None, deliberately.** The browser only talks to the web origin; the API is reached through the same-origin `/api/backend` proxy with a prefix allow-list. Do not add `CORSMiddleware`; do not expose the API port publicly | `api/backend/[...path]` |
| Start-up safety | With `COPILOT_ENV=production` the API refuses to start if the JWT secret is the default or shorter than 32 characters, or if any demo account still has its published password (unless password login is off) | `security.check_production_ready` |
| Audit | Hash-chained log of logins, failures, lockouts, rate-limit violations, questions, answers | `audit.py` |

## What leaves the building: the LLM provider

Per question the provider receives: the user's question **after PII masking**, the retrieved
passages the user is *already cleared to read*, and a fixed system prompt. It never receives
other users' data, chat history beyond the last six masked turns, documents above the user's
clearance, or unmasked national IDs/phones/accounts/cards. Embeddings and reranking run locally.
Gemini is the default; `COPILOT_LLM_PROVIDER=anthropic` switches provider (it answers without
token streaming: the whole answer arrives at once).

Decisions for the bank, not the code: which provider and region are approved; a contract with
**zero data retention** and no training on prompts; a paid tier (the free tier allows about 20
requests/day per model, so answers fall back to showing source text when it runs out); and
whether confidential internal manuals may be sent to an external provider at all - if not,
use an on-premises model behind the same `LLMProvider` interface.

## Expected from the deployment

A production-shaped compose file, secrets generator and the steps to run it are in
[`deployment.md`](deployment.md).

- **TLS** terminates at a reverse proxy / ingress in front of both services. Set
  `COPILOT_ENV=production` and run the web app with `NODE_ENV=production` so cookies are `Secure`
  and HSTS is sent. Keep the API on a private network; only the web tier needs to reach it.
- **Client address**: behind a proxy, set `COPILOT_TRUST_PROXY=true` so per-address limits use
  `X-Forwarded-For`. Enable it only when the proxy overwrites that header; otherwise anyone can
  spoof it.
- **Shared limits**: the in-process limiter is per replica. With several replicas, enforce the
  same limits at the gateway or move `ratelimit.py` to Redis.
- **Secrets**: do not ship `.env`. Provide secrets from the platform's secret store, either as
  environment variables or as files under `/run/secrets/` named after the setting
  (`/run/secrets/copilot_jwt_secret`, `copilot_gemini_api_key`, `copilot_oidc_client_secret`,
  `copilot_database_url`) - they are read automatically. Rotate the JWT secret to sign everyone out.
- **Database**: separate roles for the application and for migrations/ingestion; backups
  including the audit log, with a tested restore.
- **Logging/monitoring**: forward API logs and the audit events `login_failed`, `account_locked`,
  `rate_limited`, `access_denied` to the SIEM and alert on bursts.
- **Penetration test** by the bank's security team before go-live (not something this repo can
  claim to have done).

## Dependency scan (1 Nov 2026)

| Scope | Tool | Result |
|---|---|---|
| Python (359 pinned packages, excluding torch/CUDA wheels from the PyTorch index) | `pip-audit` | no known vulnerabilities |
| Web, production dependencies | `npm audit --omit=dev` | 6 findings (2 low, 4 moderate), all inside the `shadcn` CLI's own toolchain (`ts-morph` → `minimatch`, `deepmerge`): denial-of-service class issues in a code-generation tool. The running app imports only `shadcn/tailwind.css`; none of that code runs for users. `npm audit fix` cannot resolve them (the only offered fix is a downgrade of `shadcn`), so they are **accepted and tracked**, not hidden. Revisit when `shadcn` ships updated dependencies |

torch and the NVIDIA packages were not scanned by `pip-audit` (custom index); track PyTorch
security advisories separately.

Repeat: `uv export --no-hashes --no-emit-project -o req.txt` → `uvx pip-audit -r req.txt --no-deps
--disable-pip`; `cd web && npm audit --omit=dev`. Automating this on every change belongs in CI.
