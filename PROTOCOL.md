# Portal notes

Investigated on 30 October 2026, Asia/Kolkata, at `https://urja-ops.flockenergy.tech`, using the supplied operator account. These routes are undocumented. Credentials, cookies and signing secrets aren't included in this repository.

## Discovery

`GET /` redirects to `/login`, which has an email/password form. After login, the browser showed 403 meters in pages of 20. The initial HTML had an empty table because the page loads records after hydration.

The SvelteKit JavaScript linked by the pages exposed JSON calls for search, location, energy and transformers. The Transformers page's "Export all meters" button also revealed a signed export. It returned all 403 meter records, with the same detail structure for both source builds. The service uses that export to look up individual meter details rather than parsing the HTML.

## Login

```http
POST /login
Origin: https://urja-ops.flockenergy.tech
Content-Type: application/x-www-form-urlencoded

email=<operator email>&password=<password>
```

Successful login returned HTTP 200 with this body:

```json
{"type":"redirect","status":303,"location":"/meters"}
```

The `303` is inside the JSON, not the HTTP response status. The response also sets `__Secure-better-auth.session_token` with `Max-Age=3600`, `Path=/`, `HttpOnly`, `Secure` and `SameSite=Lax`. Subsequent requests carry that cookie. Anonymous search returned 401 with `error: "unauthorized"`.

The adapter starts a new portal session for each incoming API request. It doesn't keep sessions between requests or renew an expired session automatically. Actual expiry and key-rotation timing weren't established.

## Data routes

| Route | Observed response |
| --- | --- |
| `GET /portal/meters/search?q=&page=1` | Meter summaries, `total`, `page`, `pageSize` |
| `GET /meters/{id}` | HTML containing nameplate and hierarchy data |
| `GET /portal/meters/{id}/geo` | Latitude and longitude as strings |
| `GET /portal/meters/{id}/energy` | Readings with string timestamps and numeric values |
| `GET /portal/dts?page=1` | Transformer directory; 40 records over two pages |
| `GET /portal/keys` | `data.signingSecret` |
| `GET /portal/export?page=1` | Full meter records in `data`, plus `total` |

Search summaries contain `meterId`, `serialNo`, `make`, `phaseType`, `installStatus` and `dtCode`. Search pages start at 1 and contained 20 records each.

The adapter calls search, keys, export and energy. The detail HTML, geo and transformer routes helped establish how the portal works but aren't needed by the final API.

## Export signature

The browser computes a lowercase hex HMAC-SHA256 digest using the UTF-8 bytes of `signingSecret`. The message is:

```text
GET\n/portal/export\npage=1\n<unix-seconds>
```

Each `\n` means a newline byte. Send the timestamp as `x-timestamp` and the digest as `x-signature`. The signed query string must match the request's query string. The key comes from the logged-in UI's normal export flow.

An unsigned export returned 401 with `error: "signature_invalid"`. Timestamp tolerance and key rotation remain unknown. The browser sends `page=1`, which returned all 403 rows and `total: 403`; other export page values weren't investigated.

Exported fields are `meterId`, `serialNo`, `make`, `phaseType`, `installStatus`, `installType`, `build`, `dtCode`, `hierarchy` and `geo`. Each hierarchy level has a name and code. Coordinates are numeric `lat` and `lng` values. No recent consumption is included in the export, so that comes from the energy route.

## Quirks

Legacy detail pages, such as J100000, use label/value pairs:

```json
{"data":[{"parameterName":"Meter ID","parameterValue":"J100000"}]}
```

V2 pages, such as J100004, contain a JSON string inside `classData`:

```json
{"classData":"{\"installed_meter\":{\"MeterId\":\"J100004\",\"Make\":\"Genus\"}}"}
```

Both contain serial number, make, phase and installation fields. The export removes this format difference. The inspected data contained 238 legacy and 165 v2 meters.

Fourteen meters had a blank hierarchy code despite having a name. DT-007 also had two names: `Sanganer DT 7` in the directory and `Old Malviya Nagar Xfmr` on three meters. Some node codes appeared under different parents. The API preserves each meter's reported path without trying to resolve those differences.

## Readings

A sample energy row:

```json
{"timestamp":"24/06/2026 00:00","kwh":"48439.16","kvah":"52314.29","voltR":"229"}
```

Timestamps use `DD/MM/YYYY HH:MM` without a timezone. Both sampled builds returned 337 readings at 30-minute intervals, from 23 June 2026 23:30 to 30 June 2026 23:30. The default window therefore appears tied to the dataset rather than the current date.

The register values increased between rows. J100000 went from 48,438.74 to 48,580.79 kWh, a difference of 142.05 kWh. This supports treating the values as cumulative registers, but meter multipliers and billing semantics weren't established. Historical date parameters, energy pagination and tariffs also remain unknown. The API only reads the default window.

A request for a nonexistent meter's energy returned 404 with `error: "not_found"` and `message: "Meter not found"`. The investigation didn't modify portal data or deliberately trigger outages or rate limits.
