# Portal notes

Checked on 30 October 2026, Asia/Kolkata, at `https://urja-ops.flockenergy.tech` with the supplied operator account. These are undocumented portal routes, so their behavior may change. Credentials, cookies, signing secrets and downloaded datasets aren't included in the repo.

## Finding the data

`GET /` redirects to `/login`, which has an email/password POST form. After login, the browser showed 403 meters in pages of 20. The initial HTML still had an empty table: the page loads its records after hydration. An HTML-only scraper would miss them.

The SvelteKit JavaScript linked by the pages contained the meter search, transformer, location and energy calls. Meter detail HTML also contained the server-loaded nameplate and hierarchy data.

The useful discovery was the Transformers page's "Export all meters" button. Its handler fetches a signing secret, computes an HMAC and calls the export route. Repeating that request with the logged-in session returned the whole catalog. The key comes from the same normal UI flow.

Responses were compared with the UI and sampled across both `legacy` and `v2` meters. Both transformer pages were fetched. An anonymous search and a read for a nonexistent meter established the basic error responses. The investigation didn't modify portal business data.

## Login

```http
POST /login
Origin: https://urja-ops.flockenergy.tech
Content-Type: application/x-www-form-urlencoded

email=<operator email>&password=<password>
```

Successful login returned HTTP 200 with this SvelteKit action body:

```json
{"type":"redirect","status":303,"location":"/meters"}
```

That `303` is in the JSON; it isn't the HTTP status in the observed response. Login also sets `__Secure-better-auth.session_token`, with `Max-Age=3600`, `Path=/`, `HttpOnly`, `Secure` and `SameSite=Lax`. Later requests carry that cookie.

Anonymous search returned 401 with `error: "unauthorized"`. The cookie advertises a one-hour lifetime, but real expiry and revocation weren't observed during the live checks. The client keeps a cookie jar and renews login and the signing key once after a 401/403 or redirect to `/login`. Tests cover that recovery. It also accepts a conventional HTTP 303 login response, provided it points to `/meters` and sets a session cookie.

The UI signs out through `POST /api/auth/sign-out`. The adapter doesn't use it.

## Read routes

| Route | Response |
| --- | --- |
| `GET /portal/meters/search?q=&page=1` | `data`, `total`, `page`, `pageSize`; 20 summaries per page |
| `GET /meters/{id}` | HTML with nameplate and hierarchy data |
| `GET /portal/meters/{id}/geo` | `data.latitude` and `data.longitude`, strings in the samples |
| `GET /portal/meters/{id}/energy` | `data` array; timestamp and numeric fields are strings |
| `GET /portal/dts?page=1` | `data`, `total`, `page`, `pageSize`; 40 transformers over two pages |
| `GET /portal/keys` | `data.signingSecret` |
| `GET /portal/export?page=1` | Signed request; response contains `data` and `total` |

Meter summaries contain `meterId`, `serialNo`, `make`, `phaseType`, `installStatus` and `dtCode`. The browser encodes the search query, pages through results and debounces input by 250 ms. The adapter searches its copy of the full export instead, which also allows combined attribute filters and nearby queries.

## Signed export

The signature is a lowercase hex HMAC-SHA256 digest. Use the UTF-8 bytes of `signingSecret` as the key and this exact message:

```text
GET\n/portal/export\npage=1\n<unix-seconds>
```

Each `\n` above means a newline byte. Send the Unix timestamp as `x-timestamp` and the digest as `x-signature`. The query string on the request must match the one in the signature.

The browser sends `page=1`. That request returned all 403 rows with `total: 403` and no page metadata. Other page values weren't investigated. The adapter uses the same request and checks completeness instead of assuming the export is paginated.

An unsigned request returned 401 with `error: "signature_invalid"`. The timestamp tolerance and key-rotation interval are unknown. The client signs each operation and renews the session/key once after rejection; the host clock needs to be correct.

Each exported meter has:

```text
meterId, serialNo, make, phaseType, installStatus, installType, build,
dtCode, hierarchy, geo
```

`hierarchy` contains `zone`, `circle`, `division`, `subdivision`, `substation`, `feeder` and `dt`, each with a name and code. `geo` contains numeric `lat` and `lng`. Those fields avoid parsing display text such as `Feeder 7 (F-007)`.

The adapter serves individual meter details and locations from this export too. It doesn't fetch the detail page or `/geo` for every lookup, so those responses can lag the portal by the catalog TTL.

## Two nameplate formats

Legacy meter `J100000` used a list of label/value pairs. An excerpt:

```json
{"data":[{"parameterName":"Meter ID","parameterValue":"J100000"}]}
```

The other labels covered serial number, make, phase, installation status and installation type.

V2 meter `J100004` used a JSON string inside `classData`:

```json
{"classData":"{\"installed_meter\":{\"MeterId\":\"J100004\",\"Make\":\"Genus\"}}"}
```

Its full object also had `SerialNo`, `PhaseType`, `InstallationStatus` and `InstallationType`. The page checks for `classData` and parses it. The export already puts both builds into the same shape, which is why this service doesn't need both page parsers. The snapshot contained 238 legacy and 165 v2 meters.

## The hierarchy isn't a tree

There were 403 unique meter IDs and 40 transformer codes. Fourteen meters had a blank hierarchy code despite having a name. The missing codes occurred at circle, feeder and substation levels.

`DT-007` had two names: `Sanganer DT 7` in the transformer directory, and `Old Malviya Nagar Xfmr` on `J100400`, `J100401` and `J100402`. Grouping by name would split that transformer into two assets.

Grouping by level and code revealed another problem: 60 nodes had more than one parent. The graph keeps those relationships so a caller can inspect the disagreement. It doesn't decide which parent is right.

The resulting graph had 131 nodes and 73 issues: 60 multiple-parent flags, 12 provisional missing-code nodes and one name conflict. Fourteen affected meters can share 12 provisional nodes because some have the same parent and label. The transformer directory agreed with meter feeder codes in this snapshot; tests also cover cases where they disagree. None of these counts are hardcoded.

## Readings

An example row:

```json
{"timestamp":"24/06/2026 00:00","kwh":"48439.16","kvah":"52314.29","voltR":"229"}
```

Timestamps use `DD/MM/YYYY HH:MM` with no timezone. Both sampled meters returned 337 readings at 30-minute intervals, from 23 June 2026 23:30 to 30 June 2026 23:30. Since the inspection took place in October, the default window appears tied to the dataset. It shouldn't be described as the last seven days from today.

The kWh and kVAh values increased from one row to the next. That suggests cumulative registers. J100000 went from 48,438.74 to 48,580.79 kWh, a difference of 142.05 kWh over 336 intervals. J100004's accepted deltas summed to 71.04 kWh. These checks support the interpretation but don't establish billing semantics or meter multipliers.

The UI uses a truthiness fallback when displaying values, which could hide a numeric zero if the upstream types change. The adapter keeps zero, flags bad values and duplicate timestamps, and skips consumption deltas around gaps or register decreases. Those cases were tested with synthetic data; they weren't all present in the two live samples.

The detail page requested energy without date parameters. Historical date ranges, energy pagination, multipliers and tariffs weren't established. The API's `start` and `end` filters work on the default response and include its available bounds.

## Errors and open questions

A nonexistent meter's energy route returned 404 with `error: "not_found"` and `message: "Meter not found"`. In the adapter, broken identity or response structure fails the request; a bad individual measurement gets a null value and an issue flag.

Live checks didn't trigger rate limits or server failures, wait for expiry, probe arbitrary routes or fetch every meter's readings. Mock transports cover retries, timeouts, key renewal and malformed responses. A portal change can break these calls. The HTTP client lives in `portal.py` and the parsing code in `normalize.py`, which keeps the places to investigate fairly small.
