"""HTTP calls used by the portal's login, meter list, export and readings pages."""

import hashlib
import hmac
import time
from urllib.parse import quote, urlencode

import httpx

from .config import Settings
from .errors import ServiceError, protocol_error


def sign_request(path: str, query: str, timestamp: str, secret: str) -> str:
    message = f"GET\n{path}\n{query}\n{timestamp}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class PortalClient:
    """One client/session per incoming API request, closed by the route dependency."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self._authenticated = False

    async def close(self):
        await self.http.aclose()

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self.http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise ServiceError(
                "upstream_timeout", "Portal request timed out.", 504
            ) from None
        except httpx.RequestError:
            raise ServiceError(
                "upstream_unavailable", "Portal could not be reached.", 503
            ) from None

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            raise protocol_error() from None
        if not isinstance(payload, dict):
            raise protocol_error()
        return payload

    async def _login(self):
        response = await self._send(
            "POST",
            "/login",
            data={
                "email": self.settings.username,
                "password": self.settings.password.get_secret_value(),
            },
            headers={"Origin": self.settings.base_url},
        )
        if response.status_code != 200:
            raise ServiceError("upstream_auth_failed", "Portal login failed.")
        data = self._json(response)
        has_cookie = any(
            c.name.endswith("session_token") for c in self.http.cookies.jar
        )
        if (
            data.get("type") != "redirect"
            or data.get("location") != "/meters"
            or not has_cookie
        ):
            raise ServiceError(
                "upstream_auth_failed",
                "Portal login failed; check service credentials.",
            )
        self._authenticated = True

    async def get(
        self, path: str, params: dict | None = None, *, signed: bool = False
    ) -> dict:
        if not self._authenticated:
            await self._login()
        query = urlencode(params or {})
        headers = {}
        if signed:
            keys = await self.get("/portal/keys")
            if not isinstance(keys.get("data"), dict):
                raise protocol_error()
            secret = keys["data"].get("signingSecret")
            if not isinstance(secret, str) or not secret:
                raise protocol_error()
            timestamp = str(int(time.time()))
            headers = {
                "x-timestamp": timestamp,
                "x-signature": sign_request(path, query, timestamp, secret),
            }
        response = await self._send(
            "GET", path + ("?" + query if query else ""), headers=headers
        )
        if response.status_code in (401, 403):
            raise ServiceError(
                "upstream_auth_failed", "Portal rejected authentication or signing."
            )
        if response.status_code == 404:
            raise ServiceError("not_found", "Meter does not exist.", 404)
        if response.status_code == 429 or response.status_code >= 500:
            raise ServiceError(
                "upstream_unavailable", "Portal is temporarily unavailable.", 503
            )
        if response.status_code != 200:
            raise ServiceError("upstream_error", "Portal rejected the read request.")
        return self._json(response)

    async def search(self, query: str, page: int) -> dict:
        return await self.get("/portal/meters/search", {"q": query, "page": page})

    async def meter(self, meter_id: str) -> dict:
        # The export has one consistent detail format for both legacy and v2 meters.
        payload = await self.get("/portal/export", {"page": 1}, signed=True)
        rows = payload.get("data")
        if not isinstance(rows, list) or type(payload.get("total")) is not int:
            raise protocol_error()
        if len(rows) != payload["total"]:
            raise ServiceError("incomplete_export", "Portal export is incomplete.")
        found = None
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("meterId"), str):
                raise protocol_error()
            key = row["meterId"].strip()
            if not key or key in ids:
                raise protocol_error()
            ids.add(key)
            if key == meter_id:
                found = row
        if found is None:
            raise ServiceError("not_found", "Meter does not exist.", 404)
        return found

    async def readings(self, meter_id: str) -> dict:
        return await self.get(f"/portal/meters/{quote(meter_id, safe='')}/energy")
