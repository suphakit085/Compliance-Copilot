# Deployment & operations

How to run Compliance Copilot outside a laptop, what to watch, how to back it up, and what
hardware it needs. Security settings are in [`security.md`](security.md); data ownership in
[`governance.md`](governance.md).

## 1. Containers

| Image | Built from | Size | Notes |
|---|---|---|---|
| `compliance-copilot-api` | `Dockerfile` (repo root) | 2.2 GB (CPU PyTorch) | runs as uid 10001; models are **not** in the image |
| `compliance-copilot-web` | `web/Dockerfile` | 0.4 GB | Next.js standalone server, runs as `node` |

```bash
docker build -t compliance-copilot-api .
docker build -t compliance-copilot-web web
# GPU build of the API: --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu130
```

The lock file pins the CUDA build of PyTorch used for local development; the image installs
PyTorch from the index chosen at build time (CPU by default) **before** the other packages, so
nothing pulls the 3 GB CUDA wheels into a CPU image. All other packages are the locked versions.

### Production-shaped stack

```bash
deploy/make-secrets.sh                      # random DB password, JWT secret, metrics token
echo -n "<LLM key>" > deploy/secrets/copilot_gemini_api_key   # optional; empty = retrieval-only
docker compose -f deploy/docker-compose.prod.yml up -d
docker compose -f deploy/docker-compose.prod.yml exec api copilot create-user admin   # first admin
docker compose -f deploy/docker-compose.prod.yml exec api copilot fetch
docker compose -f deploy/docker-compose.prod.yml exec api copilot ingest
```

- Only the web port is published. The API and database live on internal networks; the
  database network has no internet route.
- Containers run read-only, with all Linux capabilities dropped and `no-new-privileges`.
- Secrets are files mounted at `/run/secrets/` (read automatically by the API), never
  environment variables or image layers. `deploy/secrets/` is git-ignored.
- `COPILOT_ENV=production` is set, so the API refuses to start with a weak JWT secret or demo
  accounts that still have their published passwords.
- The first start downloads the retrieval models (~4.5 GB) into the `models` volume; `/ready`
  stays 503 until they are loaded. After that set `HF_HUB_OFFLINE=1`.
- Put TLS in front of the web port (reverse proxy or ingress) and set `COPILOT_ALLOWED_HOSTS`.

### Verified locally (1 Nov 2026)

The production stack above was run end to end on the development machine (CPU image, models
mounted read-only from the local cache, data restored from a `backup.sh` dump):

- the API **refused to start** while the restored data still contained demo accounts with
  published passwords; after deactivating them and creating an admin with `copilot create-user`
  it started and became healthy - the JWT secret, database URL and metrics token were read from
  the secret files;
- through the published web port only: demo login refused, admin login set a `Secure; HttpOnly;
  SameSite=lax` cookie, responses carried the strict CSP (no `unsafe-eval`) and HSTS, a streamed
  question returned stage/sources/final events (source text only - no LLM key in that stack) and
  was audited; the API port was not reachable from the host;
- Prometheus scraped the API with the bearer token, loaded all 12 alert rules and showed the chat
  counter and the audit watchdog result (chain valid, 471 records).

Restoring into a **new** cluster: create the row-level-security role first
(`CREATE ROLE copilot_reader NOLOGIN`), then `pg_restore --no-owner`; roles are cluster-wide and
are not part of a database dump.

## 2. CI/CD (`.github/workflows/`)

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every push / PR | ruff + unit tests (no database; integration tests skip), web type-check + lint + production build, both images build |
| `integration.yml` | push to main, weekly, on demand | Postgres + pgvector service, fetch and verify the corpus, ingest, **all** tests, then a **retrieval quality gate**: production Hit@6 ≥ 0.95 on the main set and ≥ 0.90 on the held-out set (`copilot eval --no-e2e --min-hit6`) - no LLM key needed |
| `scheduled.yml` | weekly | `copilot check-updates` (fails if a regulator changed a pinned document), `pip-audit`, `npm audit` |
| `dependabot.yml` | weekly/monthly | dependency, base-image and action updates |

Deployment (pushing images to the bank's registry and rolling them out) is deliberately not in
this repository: it depends on the target platform and its change-approval process.
The workflows pass `actionlint`. Their first run on GitHub found two problems that local checks
had hidden, both fixed: route types (`PageProps`/`LayoutProps`) only exist after `next typegen`, so
a clean checkout failed the type check; and `www.ocs.go.th` omits its intermediate certificate,
which Windows fetches silently but Linux does not - the intermediate is now shipped in `config/ca/`
(verification stays on, see its README).

## 3. Monitoring

`GET /metrics` (Prometheus format) is enabled by setting `COPILOT_METRICS_TOKEN` and requires
it as a bearer token. `docker compose -f deploy/docker-compose.prod.yml --profile monitoring up -d
prometheus` starts a Prometheus with the scrape config and alert rules in `deploy/prometheus/`
(validated with `promtool`). Besides availability and latency, the metrics answer the questions
that matter for a compliance assistant:

| Metric | Why |
|---|---|
| `copilot_chat_total{status}` | share of answered / abstained / blocked / unverified / source-text-only answers |
| `copilot_citations_total`, `copilot_citations_verified_total` | is the model still quoting its sources verbatim? (baseline ~97%) |
| `copilot_llm_errors_total{kind}` | quota exhausted vs provider failures |
| `copilot_stream_resets_total` | provider dropping streams (Gemini 503 "high demand") |
| `copilot_audit_chain_valid` | the audit log is re-verified every hour in the background; 0 = tampering |
| `copilot_login_failures_total`, `copilot_rate_limited_total` | password guessing, abusive clients |

Alert rules (`deploy/prometheus/alerts.yml`): API down, 5xx > 2%, p95 answer time > 30 s,
**audit chain broken**, audit chain not verified for 2 h, citation verification < 90%, unverified
answers > 5%, abstention > 40%, LLM degraded, frequent stream restarts, password guessing,
rate-limit spikes.

Logs: `COPILOT_LOG_FORMAT=json` (the image default) writes one JSON object per line with a
request id (`X-Request-ID`, also returned to the client) - ship them to the SIEM. Request bodies,
query strings and ids inside URLs are never logged; the access log records the route template.
Probes: `/health` for liveness, `/ready` for readiness.

## 4. Backup & restore

```bash
DB_CONTAINER=<postgres container> deploy/backup.sh backups/          # pg_dump + sha256, 30-day retention
DB_CONTAINER=<postgres container> deploy/restore-test.sh backups/copilot-<stamp>.dump
```

One database holds everything (documents, vectors, users, chat history, audit log), so one dump
is a consistent backup. `restore-test.sh` restores into a scratch database, compares row counts
with the live one, checks the row-level-security policies came back, and re-verifies the audit
hash chain on the restored copy with the application's own code, then drops the scratch DB.

Tested on 1 Nov 2026: a 6.4 MB dump restored with all six tables matching, both RLS policies
present and the audit chain valid over 471 records. Encrypt dumps before they leave the host and
keep `deploy/secrets/` in a separate, access-controlled backup - a dump is useless without it,
and dangerous with it.

## 5. Capacity (measured)

`copilot bench` measures the part of answering that runs on your hardware: query embedding,
hybrid search and cross-encoder reranking. The LLM call (2-6 s on Gemini Flash) is external and
adds to these numbers; it does not use local resources.

Measured 1 Nov 2026 on the development machine (RTX 4060 Ti 8 GB; corpus of 1,117 passages),
32 golden-set questions per level, models warm:

| Device | Simultaneous questions | p50 | p95 | Throughput |
|---|---|---|---|---|
| GPU | 1 | 0.52 s | 1.0 s | 1.8 /s |
| GPU | 2 | 0.96 s | 1.9 s | 1.9 /s |
| GPU | 4 | 1.8 s | 3.6 s | 2.0 /s |
| GPU | 8 | 3.5 s | 5.5 s | 2.0 /s |
| CPU only | 1 | 11.4 s | 12.8 s | 0.09 /s |
| CPU only | 4 | 41.7 s | 47.9 s | 0.09 /s |

Peak GPU memory: 4.46 GiB. Model load: ~20 s from a warm disk cache.

What this means:

- **One API process serves about two questions per second of retrieval**, whatever the number of
  users, because embedding and reranking share one model instance behind a lock. Additional users
  wait in line: at 8 simultaneous questions retrieval takes ~3.5 s instead of ~0.5 s. With LLM
  time included, a single GPU process comfortably serves a team of a few dozen compliance staff,
  not a whole bank.
- **Memory:** the two models take ~4.5 GiB of GPU memory in fp32. An 8 GB card holds one API
  process, not two (a second copy pushed this card into paging, with 45-second stalls).
- **Scaling out:** run more API replicas, one per GPU (or per large CPU node), behind the web tier;
  move rate limits to the gateway or Redis (they are per process). Halving memory with fp16
  models and batching concurrent requests are the next optimisations; neither has been done.
- **CPU-only is for demos and tests only.** It works (it is the default image, so it runs
  anywhere), but retrieval takes ~11 s per question - about 20x the GPU - and four simultaneous
  questions take ~40 s each. Plan a GPU (8 GB is enough for one API process) for any real use.
