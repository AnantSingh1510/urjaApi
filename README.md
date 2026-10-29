# Urja Meter API

A Python/FastAPI service that exposes meter search, meter details and recent readings from Urja Meter Ops. Meter details include coordinates and the network path reported by the portal.

## Setup

Use Python 3.11 or newer. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
cp .env.example .env
```

Put the credentials supplied with the assignment in `.env`:

```dotenv
URJA_USERNAME=<operator email>
URJA_PASSWORD=<password>
```

Then start the service:

```sh
uvicorn urja_api.app:app --host 127.0.0.1 --port 8000
```

Credentials are required. `.env` is ignored by Git. The service is intended to run locally and doesn't implement its own user authentication.

## API

| Request | Result |
| --- | --- |
| `GET /v1/meters?q=J100&page=1` | Search by meter ID or serial number |
| `GET /v1/meters/{meter_id}` | Nameplate, coordinates and reported hierarchy |
| `GET /v1/meters/{meter_id}/readings` | Recent register readings and interval kWh |

For example:

```sh
curl 'http://127.0.0.1:8000/v1/meters?q=J100000&page=1'
curl 'http://127.0.0.1:8000/v1/meters/J100000'
curl 'http://127.0.0.1:8000/v1/meters/J100000/readings'
```

Search uses the portal's pagination: pages start at 1, and the response contains `data`, `total`, `page` and `page_size`. The observed page size is 20. Leaving `q` empty lists meters. Details are under `data`; readings include `meter_id`, `timezone`, `available_from`, `available_to` and `data`.

[openapi.json](openapi.json) describes the requests, response fields and errors. [PROTOCOL.md](PROTOCOL.md) explains the portal login and data routes. The required questions are answered in [REFLECTION.md](REFLECTION.md).

## Structure

```text
urja_api/
  app.py         The three API routes
  portal.py      Login and portal HTTP requests
  normalize.py   Convert portal fields and readings
  models.py      Response schemas
  config.py      Environment settings
  errors.py      Portal error mapping
```

Each API request opens a portal client, logs in, reads the requested data and closes the client. Search uses the portal's search route. Details use its signed export, which gives the same fields for legacy and v2 meters. Readings use the per-meter energy route.

The export is an internal way to retrieve details, not a separate bulk-download feature. Fetching it for each lookup costs more bandwidth than caching, but keeps the service small and avoids parsing two HTML detail formats. It must contain its stated row count and unique meter IDs before a lookup can return a result.

## Assumptions and decisions

The portal's kWh/kVAh values increase over time, so the API calls them `cumulative_kwh` and `cumulative_kvah`. `interval_kwh` is the difference between valid readings exactly 30 minutes apart. The first reading has no delta. Missing values, duplicate timestamps, gaps and register decreases produce null deltas with issue flags. Zero remains a valid reading. These figures aren't validated billing totals.

Timestamps have no offset. The service assumes `Asia/Kolkata` because the network is in Jaipur. The sampled default window ended on June 30, 2026, even though the investigation took place in October. The API returns the available bounds and doesn't claim the data is current or fetch older history.

Meter hierarchy names and codes are returned as supplied. Empty codes become null; conflicting labels aren't merged into a reconstructed network. Invalid coordinates become null with an issue flag.

Portal failures return an `error` object with `code` and `message`: 404 for a missing meter, 502 for authentication or response-format problems, 503 for an unavailable portal, and 504 for a timeout. FastAPI returns 422 for invalid request parameters. Credentials and raw portal error bodies aren't returned to callers.

## Configuration

| Variable | Default |
| --- | --- |
| `URJA_USERNAME`, `URJA_PASSWORD` | Required |
| `URJA_BASE_URL` | `https://urja-ops.flockenergy.tech` |
| `URJA_PORTAL_TIMEZONE` | `Asia/Kolkata` |
| `URJA_TIMEOUT_SECONDS` | `15` for HTTP connect/read/write/pool operations |

TLS verification stays enabled. The client doesn't automatically follow redirects or retry failed reads.

## Scope

This repository contains the API source, setup files, README, protocol notes, reflection and OpenAPI document. It doesn't include a test suite, CI, Docker setup, demo mode or Swagger UI. The optional extensions are left out: caching, a local query index, spatial search, a reconstructed network graph, automatic session recovery and a separate frontend.

With more time, the first questions to resolve would be historical date-range support and whether the register interpretation holds across more meters. Caching could then reduce repeated logins and export downloads. The undocumented portal routes remain the main maintenance risk.

To regenerate the required OpenAPI file after editing the API:

```sh
python scripts/export_openapi.py
```
