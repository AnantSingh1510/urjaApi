# Urja Meter API

A small FastAPI service for reading data from Urja Meter Ops. It exposes meter details, locations, network relationships and energy readings as JSON.

The portal has no documented API, but its web pages use JSON endpoints. This service logs in with the operator account and calls those endpoints directly. A bulk export provides the meter catalog, so there's no browser to run and no need to scrape each meter page.

## Run it locally

Use Python 3.11 or newer. The setup below starts with synthetic data, so you can try it without portal credentials. Python 3.12 is the recommended version.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cp .env.example .env
uvicorn urja_api.app:app --host 127.0.0.1 --port 8000
```

Open [Swagger UI](http://127.0.0.1:8000/docs), or make a request:

```sh
curl 'http://127.0.0.1:8000/v1/meters?status=Installed&limit=2'
curl 'http://127.0.0.1:8000/v1/meters/DEMO-001/readings?limit=2'
```

The demo generates 12 meters locally. Responses identify them with `freshness.source: "synthetic_demo"`; they aren't copies of portal records. There's no database or paid service to set up.

### Use the live portal

Change these values in `.env`, using the credentials from the assignment:

```dotenv
URJA_DEMO=false
URJA_USERNAME=<operator email>
URJA_PASSWORD=<password>
```

Restart the server, then try:

```sh
curl 'http://127.0.0.1:8000/v1/summary'
curl 'http://127.0.0.1:8000/v1/meters/J100000'
curl 'http://127.0.0.1:8000/v1/meters/J100000/readings?limit=2'
```

The first data request logs in and loads the catalog. Live mode requires credentials and won't fall back to demo data. Git and Docker both ignore `.env`.

For access beyond localhost, set `URJA_API_KEY` and send it in the `X-API-Key` header. Swagger's Authorize button accepts the same key. The key protects `/v1` routes; `/healthz` remains public. A public deployment would also need TLS, user authorization and ingress rate limits.

## Endpoints

| Route | Returns |
| --- | --- |
| `GET /healthz` | Process status, without contacting the portal |
| `GET /v1/summary` | Meter and transformer counts, status/make breakdowns, issue counts |
| `GET /v1/meters` | Filtered, paginated meters |
| `GET /v1/meters/{meter_id}` | Nameplate, location, hierarchy and any data issues |
| `GET /v1/meters/{meter_id}/readings` | Cumulative registers and calculated interval consumption |
| `GET /v1/transformers` | Paginated transformer directory |
| `GET /v1/network` | Network nodes, parent relationships and conflicts |
| `GET /openapi.json` | OpenAPI 3.1 schema |
| `GET /docs` | Swagger UI |

[openapi.json](openapi.json) is generated from the application. [PROTOCOL.md](PROTOCOL.md) explains the portal calls and the quirks found during investigation. The [reflection](REFLECTION.md) covers assumptions and trade-offs; [verification notes](VERIFICATION.md) record what was tested.

### Search and nearby meters

`q` searches meter IDs and serial numbers by substring. The other text filters (`make`, `status`, `phase`, `transformer_code`) use case-insensitive exact matches. All supplied filters must match.

These examples use live data:

```sh
curl --get 'http://127.0.0.1:8000/v1/meters' \
  --data-urlencode 'make=Genus' --data-urlencode 'status=Installed' \
  --data-urlencode 'phase=three' --data-urlencode 'limit=20'

curl --get 'http://127.0.0.1:8000/v1/meters' \
  --data-urlencode 'latitude=26.9' --data-urlencode 'longitude=75.8' \
  --data-urlencode 'radius_km=5'
```

Nearby search needs all three geographic parameters. It uses haversine distance and sorts by distance, then meter ID. Other searches sort by ID. Filtering happens before pagination: `offset` starts at zero, and `limit` defaults to 50 with a maximum of 200. An offset past the last result returns an empty list and the full matching count.

Pagination uses the cached catalog. If that catalog refreshes between requests, page boundaries can move; there are no snapshot cursors.

### Energy readings

The portal's kWh and kVAh values look like cumulative registers. Adding those values would give the wrong consumption figure. The API keeps them as `cumulative_kwh` and `cumulative_kvah`, then calculates `interval_kwh` from adjacent readings.

A delta is only calculated when both kWh values are valid, their timestamps are unique and exactly 30 minutes apart, and the register hasn't decreased. Zero counts as a valid value. Gaps, missing values, duplicate timestamps and resets are flagged instead of filled in.

For example, the second demo reading is:

```json
{
  "timestamp": "2026-06-30T00:30:00+05:30",
  "raw_timestamp": "30/06/2026 00:30",
  "cumulative_kwh": 1000.4,
  "cumulative_kvah": 1080.43,
  "voltage_r_v": 226.0,
  "interval_kwh": 0.4,
  "issues": []
}
```

You can filter the returned window with inclusive `start` and `end` timestamps. Both need a timezone offset:

```sh
curl --get 'http://127.0.0.1:8000/v1/meters/J100000/readings' \
  --data-urlencode 'start=2026-06-24T00:00:00+05:30' \
  --data-urlencode 'end=2026-06-24T23:30:00+05:30'
```

These filters don't fetch older history. `available_from` and `available_to` show the window the portal actually returned. In the live samples, that window ended on June 30 even though the investigation happened in October.

The first filtered reading has no delta. `valid_interval_kwh` sums accepted deltas across the filtered window before pagination, so it can exclude periods with bad data. It isn't a billing total. Readings default to 500 rows per page, with a maximum of 2,000; a later page may start with a delta calculated against the previous page's last row. Rows with invalid timestamps are retained without date filters and excluded when those filters are present.

The portal supplies no timezone. The service assumes `Asia/Kolkata` based on the Jaipur network; you can change it with `URJA_PORTAL_TIMEZONE`. The register interpretation and 30-minute cadence also come from the sampled data.

## How it's put together

```text
urja_api/
  app.py         Routes, validation, API-key checks and error responses
  portal.py      Login, cookies, export signatures and retries
  normalize.py   Meter/readings parsing, network graph and distances
  service.py     Catalog index and caches
  models.py      Response models and OpenAPI schemas
  config.py      Environment settings
  demo.py        Synthetic data
scripts/         Schema export and live smoke check
tests/           Offline tests
```

FastAPI routes call the service layer, which reads from its cache or fetches through the portal client. Normalization happens before a new catalog enters the cache.

HTTPX handles the portal session. Using its JSON routes avoids a browser dependency, and the bulk export gives the same fields for legacy and v2 meters. The two detail-page formats therefore don't need separate parsers here.

The export must contain its stated number of rows, with unique meter IDs. Transformer pages are fetched until their stated total is reached. A partial or inconsistent response fails the refresh. Reads across these endpoints aren't a portal-side transaction, though, so a concurrent edit could still produce a mismatch.

The catalog stays in memory, indexed by meter ID. Searches scan it. That's a reasonable trade-off for 403 meters; around 100,000, full exports, linear searches and a copy per worker would need measuring. That number is an estimate, not a benchmark. SQLite would be a straightforward next step for a local service, or PostgreSQL/PostGIS for larger spatial queries and multiple workers.

### Caching and failures

The catalog expires after five minutes. Readings expire after one minute, and the cache keeps at most 128 meters using LRU eviction. TTLs use a monotonic clock. `fetched_at` and `expires_at` describe the cache; they don't tell you how recent the measurements are.

An expired entry waits for a refresh. If the refresh fails, the request returns an error. The old catalog is only replaced after the new one passes validation. Locks let concurrent callers share a refresh, and portal requests run one at a time. Use one worker for this project: caches are per process.

GET requests get up to two retries for transient failures, with `Retry-After` respected. An authentication or signature rejection gets one session/key renewal. Login itself isn't retried for transient errors. HTTP requests and refresh stages have deadlines, so a failed portal call can't wait indefinitely. Cookies and signing secrets stay in memory.

Errors follow this shape:

```json
{"error":{"code":"not_found","message":"Meter does not exist.","request_id":"..."}}
```

Status codes are 401 for an invalid service key, 404 for a missing resource, 422 for invalid input, 502 for portal authentication or protocol problems, 503 for temporary unavailability, and 504 for a timeout. Responses include `X-Request-ID` and `Cache-Control: no-store`. Portal error bodies and credentials aren't passed through to callers.

### Network relationships

The graph identifies nodes by `(level, code)` and keeps every observed name and parent. Missing codes get provisional IDs based on the parent and label. This avoids guessing that two similarly named nodes are the same asset.

`meter_count` counts distinct meters at each node. Transformer-directory names become aliases, and feeder disagreements are reported. The service doesn't choose a "correct" parent or repair the source data. The graph covers paths seen on meters; `/v1/transformers` still returns directory entries that have no meters.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `URJA_DEMO` | `false`; the example file sets `true` | Use synthetic data |
| `URJA_BASE_URL` | `https://urja-ops.flockenergy.tech` | Portal origin, HTTPS only |
| `URJA_USERNAME`, `URJA_PASSWORD` | empty | Required for live mode |
| `URJA_API_KEY` | empty | Protect `/v1` routes |
| `URJA_CATALOG_TTL_SECONDS` | `300` | Catalog cache lifetime |
| `URJA_READINGS_TTL_SECONDS` | `60` | Readings cache lifetime |
| `URJA_PORTAL_TIMEZONE` | `Asia/Kolkata` | Timezone for portal timestamps |
| `URJA_TIMEOUT_SECONDS` | `15` | HTTPX connect/read/write/pool timeout |
| `URJA_OPERATION_TIMEOUT_SECONDS` | `60` | Portal operation or refresh-stage deadline |

A readings request with an empty cache may need a catalog refresh followed by a readings refresh. Each stage has its own deadline. TLS verification stays enabled, redirects aren't followed automatically, and callers can't change the portal origin through an API parameter.

## Tests

```sh
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
pytest -q
ruff check .
ruff format --check .
python scripts/export_openapi.py
git diff --exit-code openapi.json
```

The tests run offline without credentials. Mock HTTP responses cover login, signing, renewal and portal failures. The rest cover export completeness, caching, search, hierarchy conflicts and readings with missing values or resets. CI also checks that the committed OpenAPI file matches the application. The lock files pin the tested dependencies; `pyproject.toml` lists supported version ranges.

To check the real portal, put credentials in `.env` and run:

```sh
python scripts/smoke_live.py
```

This reads the catalog and one meter's readings per source build, then prints summary counts. It doesn't modify portal data or print credentials.

## Docker

```sh
docker build -t urja-api .
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 urja-api
```

The image runs as a non-root user. The Docker daemon wasn't available during local verification, so the build and run commands haven't been tested. See [VERIFICATION.md](VERIFICATION.md) for the checks that did run.

## What's left out

Swagger covers API exploration for now, so there's no custom frontend. There's also no database or background sync job at this dataset size. Writes are outside the assignment's scope, and the inconsistent hierarchy needs source clarification before automatic repairs would make sense.

Historical readings are the main functional gap: only the portal's default window is supported. The service also assumes one operator account and doesn't implement tenant or user authorization.

Next, verify date-range requests and real session expiry, then check more meters for gaps and resets. Refresh metrics and source timestamps would help with operations. If the dataset grows, persistence and spatial indexes should come before a UI for exploring the network and readings. A supported upstream API would remove much of the maintenance risk in these undocumented routes.
