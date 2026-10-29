# Urja portal protocol

Investigated on **30 October 2026 (Asia/Kolkata)** against `https://urja-ops.flockenergy.tech`, using the supplied operator account. This records observed behavior, not a vendor-supported API contract. Credentials, cookies, signing secrets and downloaded datasets are deliberately absent from this repository.

## Discovery path

1. `GET /` redirected to `/login`. The login page exposed a normal email/password POST form.
2. After login, the browser showed 403 meters, a search box, 20-row pages and a Transformers navigation link. The initial server-rendered meter HTML had an empty list; the browser populated it after hydration. Scraping only that HTML would incorrectly report zero meters.
3. The page's linked SvelteKit JavaScript contained `/portal/meters/search`, `/portal/dts`, per-meter `/geo` and `/energy` calls. The meter detail HTML included server-loaded nameplate and hierarchy values.
4. The Transformers page's **Export all meters** implementation requested `/portal/keys`, computed an HMAC in the browser, then requested `/portal/export`. Reproducing that normal authorized export returned the complete catalog in one response.
5. Responses were compared with the visible UI and sampled across both `legacy` and `v2` source builds. Transformer pages 1 and 2 were fetched. One nonexistent meter read and an unauthenticated search were used to observe error behavior. No portal business-data writes were performed.

The export is a normal logged-in UI capability. Its signing secret is obtained through that same session; it was not guessed, extracted from another user or bypassed.

## Session authentication

```http
POST /login
Origin: https://urja-ops.flockenergy.tech
Content-Type: application/x-www-form-urlencoded

email=<operator email>&password=<password>
```

Observed success used **HTTP 200** with a SvelteKit action body:

```json
{"type":"redirect","status":303,"location":"/meters"}
```

The response set `__Secure-better-auth.session_token` with `Max-Age=3600`, `Path=/`, `HttpOnly`, `Secure` and `SameSite=Lax`. Subsequent read requests carry the cookie. The max-age advertises a one-hour lifetime; actual elapsed-time expiry and server-side revocation were not tested live.

An anonymous `GET /portal/meters/search` returned a JSON `unauthorized` error: a valid session is required. The adapter keeps cookies in HTTPX's cookie jar, accepts the observed JSON redirect or a conventional HTTP 303 to `/meters`, and requires a session cookie. On a read's 401/403 or redirect to `/login`, it renews the login/key once. Recovery is covered by mock tests; those tests are not evidence of every live failure mode.

The linked UI also uses `POST /api/auth/sign-out`; the adapter does not need that route.

## Observed read routes

| Route | Response / behavior |
| --- | --- |
| `GET /portal/meters/search?q=&page=1` | `data`, `total`, `page`, `pageSize`; 20 summaries per page, 403 total observed |
| `GET /meters/{id}` | SvelteKit detail HTML with server-loaded nameplate and hierarchy |
| `GET /portal/meters/{id}/geo` | `data.latitude` / `data.longitude`, returned as decimal strings in sampled responses |
| `GET /portal/meters/{id}/energy` | `data` array of readings; strings for timestamps and numeric fields |
| `GET /portal/dts?page=1` | Transformer directory with `data`, `total`, `page`, `pageSize`; 20 per page, 40 total |
| `GET /portal/keys` | `data.signingSecret`, available to the authenticated export UI |
| `GET /portal/export?page=1` | Signed export; `data` plus `total`; all 403 rows in the sampled response |

Search summary fields were `meterId`, `serialNo`, `make`, `phaseType`, `installStatus`, `dtCode`. Search pagination, query encoding and the 250 ms debounce were visible in client code. This service instead searches the complete export locally, allowing combined attribute and geographic filters.

### Export signing

The browser's signature is lowercase hexadecimal HMAC-SHA256. The key is the UTF-8 bytes of `signingSecret`. The signed message is exactly:

```text
GET\n/portal/export\npage=1\n<unix-seconds>
```

Here `\n` denotes a newline byte, **not** two literal characters. Send the same Unix-seconds string as `x-timestamp` and the digest as `x-signature`. The query bytes must match those signed. The request uses `page=1` because that is what the normal UI sends. The response had no page metadata and already contained every row; the behavior of other export page values was not investigated or assumed.

An unsigned export returned **401** with `error: "signature_invalid"` and a message that the request signature was missing or invalid. The accepted timestamp tolerance and signing-key rotation interval were not established. Keep the host clock synchronized; the adapter regenerates signatures per operation and renews authentication/key once after rejection.

Export fields:

```text
meterId, serialNo, make, phaseType, installStatus, installType, build,
dtCode, hierarchy, geo
```

`hierarchy` is an object with `zone`, `circle`, `division`, `subdivision`, `substation`, `feeder`, `dt`; each has `name` and `code`. `geo` contains numeric `lat` and `lng`. This structured path avoids parsing display labels such as `Feeder 7 (F-007)`.

The service uses this export for individual meter responses too. It does not hit the detail or geo endpoints on each lookup. Data can therefore lag the portal by the configured catalog TTL.

## Two nameplate formats

A sampled legacy detail (`J100000`) represented nameplate fields as:

```json
{"data":[{"parameterName":"Meter ID","parameterValue":"J100000"}]}
```

The actual list also contained serial, make, phase, installation status and installation type.

A sampled v2 detail (`J100004`) used a **JSON string nested inside JSON**:

```json
{"classData":"{\"installed_meter\":{\"MeterId\":\"J100004\",\"Make\":\"Genus\"}}"}
```

The full object included `SerialNo`, `PhaseType`, `InstallationStatus` and `InstallationType`. The page's own JavaScript switches on `classData` and parses the string. The export supplies a shared flat representation for both builds; the adapter uses that instead of duplicating both page parsers. The observed export contained 238 legacy and 165 v2 meters.

## Network inconsistencies

The catalog had 403 unique meter IDs and 40 distinct transformer codes. In the observed snapshot:

- 14 meters had a blank code at a hierarchy level even though a name was present. Examples included a circle, feeder and substation. Names are not used to invent missing codes.
- `DT-007` had the directory name **Sanganer DT 7** and the alias **Old Malviya Nagar Xfmr** on three extra meters (`J100400`–`J100402`). Grouping by display name would split one transformer.
- Reconstructing identities by level and code produced 60 nodes with multiple observed parents. A strict tree would either duplicate identities or discard information.
- The graph contained 131 nodes, including 12 provisional missing-code identities; 14 affected meter records can share a provisional identity. It exposed 73 network issues: 60 multiple-parent flags, 12 missing-code flags and one name conflict. There were no observed directory-versus-meter feeder mismatches in this snapshot; synthetic tests cover that possibility.

These counts describe one inspection, not constants in the service. The graph is descriptive, and does not assert which contradictory relationship is correct.

## Energy data and its limits

Sampled energy rows used:

```json
{"timestamp":"24/06/2026 00:00","kwh":"48439.16","kvah":"52314.29","voltR":"229"}
```

`timestamp` is day-first `DD/MM/YYYY HH:MM`, without an offset. Both sampled builds returned 337 readings from **23 June 2026 23:30 to 30 June 2026 23:30**, at 30-minute spacing, despite the inspection occurring in October. The default window appears anchored to the dataset; it must not be described as the past seven days relative to today.

The kWh/kVAh values increased across adjacent readings. They are treated as cumulative registers; this is a documented inference. Sample `J100000` rose from 48,438.74 to 48,580.79 kWh, yielding 142.05 kWh across 336 accepted intervals. For `J100004`, accepted intervals summed to 71.04 kWh. These are sample checks, not billing validation.

The UI displays values with a truthiness fallback (`value || "—"`), which could hide numeric zero if upstream types change. The adapter explicitly preserves zero. It also preserves invalid rows, reports missing values, detects duplicate timestamps, and suppresses interval calculation around gaps or decreases. These edge cases were exercised with synthetic tests; they were not all observed in the two live samples.

The visible detail view issued an unparameterized energy request. No historical date-range, pagination, meter-multiplier or tariff contract was established. The clean API's date filters apply locally to that default response and report its actual available bounds.

## Failure behavior and remaining unknowns

A nonexistent meter energy request returned 404 with `error: "not_found"` and `message: "Meter not found"`. Source values that violate the expected schema cause a controlled adapter error or an explicit field issue, depending on whether identity/structure or an individual measurement is affected.

The live investigation did not deliberately induce rate limiting or server failures, wait for a real expired session, probe arbitrary endpoints, or exhaustively read energy for every meter. Retry, timeout, key-renewal and malformed-response behavior is tested against mock transports. Protocol changes are a maintenance risk; isolated client and normalization modules make those changes easier to diagnose.
