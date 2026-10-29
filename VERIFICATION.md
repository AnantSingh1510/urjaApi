# Verification

Checks run on 30 October 2026, Asia/Kolkata.

## Local tests

All 61 offline tests passed on Python 3.14 and again after installing the pinned dependencies in a fresh Python 3.12 environment. Ruff's lint and format checks passed. The OpenAPI validator accepted the schema, and regenerating `openapi.json` produced no diff.

Starlette's test client emitted one deprecation warning about HTTPX. It didn't affect the test results. CI is configured for Python 3.11, 3.12 and 3.13; hosted CI wasn't part of these local checks.

The tests cover session cookies, login failures, export signatures and key renewal, retries, `Retry-After`, timeouts and malformed responses. They also exercise transformer pagination, incomplete or duplicate exports, concurrent cache reads and expiry, geographic filters, input validation, API keys and schema drift. Reading cases include zero, missing or invalid values, duplicate or invalid timestamps, gaps and resets. Network cases cover missing codes, aliases and multiple parents.

## Live checks

The FastAPI test client exercised the application while HTTPX contacted the real portal. Summary, meter search, pagination, details, transformers and the network endpoint all returned successfully. Readings were checked for one legacy meter and one v2 meter.

| Check | Result |
| --- | --- |
| Unique meters | 403 |
| Transformers, across both portal pages | 40 |
| Statuses | 238 Installed, 90 Faulty, 75 Decommissioned |
| Builds | 238 legacy, 165 v2 |
| Meters with missing hierarchy codes | 14 |
| Network nodes | 131 |
| Multiple-parent flags | 60 |
| Provisional missing-code flags | 12 |
| Name-conflict flags | 1 |
| Readings per sampled meter | 337 |
| Sample window | 23 June 2026 23:30 to 30 June 2026 23:30, assumed Asia/Kolkata |
| J100000 interval sum | 142.05 kWh over 336 accepted intervals |
| J100004 interval sum | 71.04 kWh over 336 accepted intervals |

The API could find the last three extra meters. DT-007 kept both of its names and all 13 associated meters. These are results from that snapshot, not expected constants in the code. Expiry, throttling and outages were tested with mocks rather than induced on the live portal.

## HTTP and browser check

Uvicorn ran locally in demo mode on port 8765. HTTP requests returned the expected 12-meter summary and 18.8 kWh across 47 valid demo intervals. Swagger rendered the routes, schemas and API-key control in the browser. The README uses port 8000 so the preview isn't needed to run the project.

## Not checked

The Docker daemon wasn't available, so the container wasn't built or run. There was no performance benchmark or security audit, and readings weren't fetched for every meter. Historical date-range behavior is still unknown. This record covers local checks, not deployment or hosted CI.

## Run the checks again

```sh
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
pytest -q
ruff check .
ruff format --check .
python scripts/export_openapi.py
git diff --exit-code openapi.json
```

For a live check, configure credentials in `.env` and run `python scripts/smoke_live.py`. It reads the catalog, then fetches one meter's readings per source build.
