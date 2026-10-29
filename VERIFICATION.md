# Verification record

Verified on **30 October 2026 (Asia/Kolkata)**. Live observations are samples, not guarantees about later portal state.

## Automated checks

- **61 offline tests passed** on Python **3.14** in the development environment.
- Installed the pinned development requirements and this package in a **fresh Python 3.12 environment**; **61 tests passed** there as well.
- `ruff check .` and `ruff format --check .` passed.
- `openapi-spec-validator` accepted the generated OpenAPI 3.1 document.
- Regenerating `openapi.json` produced no Git diff. Tests also compare the checked-in schema to the runtime schema.
- The current Starlette test client emits one third-party deprecation warning about HTTPX. No warnings were hidden; no tests failed.
- CI is configured for Python 3.11, 3.12 and 3.13. Hosted CI was **not** run during local verification; local evidence covers 3.12 and 3.14 only.

Offline cases cover login action/cookie handling, signature construction, session/key renewal, bounded authentication failures, transient failures, Retry-After, timeouts, malformed JSON and key payloads, transformer pagination, truncated/duplicate export rejection, cache expiry and concurrent cold reads, filters and geographic search, missing hierarchy codes, aliases/multiple parents, invalid/duplicate timestamps, missing/zero/invalid readings, register resets, gaps, API authentication, input validation and schema drift.

## Live portal checks

The actual FastAPI application was exercised through its test client while its HTTPX adapter connected to the real portal. Successful checks included summary, filtered and paginated meter lists, details for one legacy and one v2 meter, readings for both, transformer pagination and the network graph.

| Observation | Result |
| --- | --- |
| Unique meters | 403 |
| Transformers across both upstream pages | 40 |
| Installation statuses | 238 Installed, 90 Faulty, 75 Decommissioned |
| Source builds | 238 legacy, 165 v2 |
| Meters with missing hierarchy codes | 14 |
| Reconstructed network nodes | 131 |
| Multiple-parent node flags | 60 |
| Provisional missing-code node flags | 12 |
| Conflicting-name node flags | 1 |
| Sampled readings, per meter | 337 |
| Sampled window | 23 June 2026 23:30 through 30 June 2026 23:30, assumed Asia/Kolkata |
| J100000 accepted interval consumption | 142.05 kWh across 336 intervals |
| J100004 accepted interval consumption | 71.04 kWh across 336 intervals |

The final three extra meters were reachable through the API's full inventory query. DT-007 retained both observed names and all 13 associated meters. Actual session expiration, rate limiting and upstream outages were not induced live; mock tests cover the adapter's handling of them.

## Running server and browser

Started Uvicorn locally in synthetic mode on port 8765. HTTP requests to `/v1/summary` and `/v1/meters/DEMO-001/readings` returned the expected 12-meter inventory and 18.8 kWh of accepted interval consumption across 47 demo intervals. The browser rendered Swagger UI with the expected routes, schemas and optional API-key authorization control.

This preview is a local convenience, not a deployment. The README's commands run the application independently on port 8000.

## Not verified

The Dockerfile is supplied, but a container build/run was not performed because the local Docker daemon was unavailable. No performance benchmark, security audit, exhaustive consumption crawl or arbitrary historical date-range contract was established. Public GitHub publishing and hosted CI are outside this verification record.

## Reproduce

```sh
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
pytest -q
ruff check .
ruff format --check .
python scripts/export_openapi.py
git diff --exit-code openapi.json
```

For a fresh live observation, configure credentials locally and run `python scripts/smoke_live.py`. This script uses read routes and performs at most one readings fetch per source build after loading the catalog.
