"""Only login and observed read routes are used. No DOM scraping or JS evaluation."""

import asyncio
import hashlib
import hmac
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode

import httpx

from .config import Settings
from .errors import ServiceError, protocol_error


def sign_request(path: str, query: str, timestamp: str, secret: str) -> str:
    canonical = f"GET\n{path}\n{query}\n{timestamp}"
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class PortalClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "UrjaReadOnlyAdapter/1.0"},
        )
        self._lock = asyncio.Lock()
        self._authenticated = False
        self._secret: str | None = None

    async def close(self):
        await self.http.aclose()

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        # Only idempotent GETs are retried for transient failures; login is not.
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                response = await self.http.request(method, path, **kwargs)
            except httpx.TimeoutException:
                if attempt + 1 == attempts:
                    raise ServiceError(
                        "upstream_timeout", "Portal request timed out.", 504
                    ) from None
            except httpx.RequestError:
                if attempt + 1 == attempts:
                    raise ServiceError(
                        "upstream_unavailable", "Portal could not be reached.", 503
                    ) from None
            else:
                if response.status_code not in (429, 500, 502, 503, 504):
                    return response
                if attempt + 1 == attempts:
                    raise ServiceError(
                        "upstream_unavailable", "Portal is temporarily unavailable.", 503
                    )
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (
                                parsedate_to_datetime(retry_after) - datetime.now(UTC)
                            ).total_seconds()
                        except (ValueError, TypeError):
                            delay = 0
                    if delay > 3:
                        # Do not ignore a long Retry-After or tie up callers sleeping for minutes.
                        raise ServiceError(
                            "upstream_rate_limited", "Portal requested a later retry.", 503
                        )
                    await asyncio.sleep(max(0, delay))
                    continue
            await asyncio.sleep(0.2 * 2**attempt + random.random() * 0.1)
        raise AssertionError("unreachable")

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            raise protocol_error() from None
        if not isinstance(payload, dict):
            raise protocol_error()
        return payload

    async def _login(self):
        self._authenticated = False
        self._secret = None
        self.http.cookies.clear()
        r = await self._send(
            "POST",
            "/login",
            data={
                "email": self.settings.username,
                "password": self.settings.password.get_secret_value(),
            },
            headers={"Origin": self.settings.base_url},
        )
        # SvelteKit returns a JSON redirect action with HTTP 200 in this deployment.
        if r.status_code == 200:
            data = self._json(r)
            success = data.get("type") == "redirect" and data.get("location") == "/meters"
        else:
            success = r.status_code == 303 and r.headers.get("location") == "/meters"
        if not success or not any(c.name.endswith("session_token") for c in self.http.cookies.jar):
            raise ServiceError(
                "upstream_auth_failed", "Portal login failed; check service credentials."
            )
        self._authenticated = True

    async def _get_locked(self, path: str, query: str = "", *, signed: bool = False) -> dict:
        for attempt in range(2):
            if not self._authenticated:
                await self._login()
            headers = {}
            if signed:
                if self._secret is None:
                    keys = await self._get_locked("/portal/keys")
                    secret = keys.get("data", {}).get("signingSecret")
                    if not isinstance(secret, str) or not secret:
                        raise protocol_error()
                    self._secret = secret
                timestamp = str(int(time.time()))
                headers = {
                    "x-timestamp": timestamp,
                    "x-signature": sign_request(path, query, timestamp, self._secret),
                }
            r = await self._send("GET", path + ("?" + query if query else ""), headers=headers)
            if r.status_code in (401, 403) or (
                r.status_code in (302, 303, 307)
                and r.headers.get("location", "").startswith("/login")
            ):
                if attempt == 0:
                    # Renew the session AND its signing key once. Serialized to prevent races.
                    await self._login()
                    continue
                raise ServiceError(
                    "upstream_auth_failed", "Portal rejected authentication or signing."
                )
            if r.status_code == 404:
                raise ServiceError("not_found", "Requested resource does not exist.", 404)
            if r.status_code != 200:
                raise ServiceError("upstream_error", "Portal rejected the read request.")
            return self._json(r)
        raise AssertionError("unreachable")

    async def get(self, path: str, params: dict | None = None, *, signed: bool = False) -> dict:
        try:
            async with asyncio.timeout(self.settings.operation_timeout_seconds):
                async with self._lock:
                    return await self._get_locked(path, urlencode(params or {}), signed=signed)
        except TimeoutError:
            raise ServiceError(
                "upstream_timeout", "Portal operation exceeded its deadline.", 504
            ) from None

    async def export_meters(self) -> dict:
        return await self.get("/portal/export", {"page": 1}, signed=True)

    async def transformers(self) -> list[dict]:
        rows: list[dict] = []
        expected = None
        # Bounded sequential paging, explicit completeness checks, no guessed page size.
        for page in range(1, 1001):
            data = await self.get("/portal/dts", {"page": page})
            if not isinstance(data.get("data"), list) or type(data.get("total")) is not int:
                raise protocol_error()
            if expected is None:
                expected = data["total"]
            if data["total"] != expected or data.get("page") != page:
                raise protocol_error()
            rows.extend(data["data"])
            if len(rows) == expected:
                return rows
            if not data["data"] or len(rows) > expected:
                raise protocol_error()
        raise protocol_error()

    async def readings(self, meter_id: str) -> dict:
        return await self.get(f"/portal/meters/{quote(meter_id, safe='')}/energy")
