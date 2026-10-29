import hashlib
import hmac

import httpx
import pytest

from urja_api.config import Settings
from urja_api.errors import ServiceError
from urja_api.portal import PortalClient, sign_request


def live_settings():
    return Settings(username="test@example.invalid", password="test-password", _env_file=None)


def login_response(token="one"):
    return httpx.Response(
        200,
        json={"type": "redirect", "status": 303, "location": "/meters"},
        headers={
            "set-cookie": f"__Secure-better-auth.session_token={token}; Path=/; Secure; HttpOnly"
        },
    )


def test_signature_matches_independent_hmac_vector():
    actual = sign_request("/portal/export", "page=1", "12345", "secret")
    expected = hmac.digest(b"secret", b"GET\n/portal/export\npage=1\n12345", hashlib.sha256).hex()
    assert actual == expected
    assert actual != sign_request("/portal/export", "page=2", "12345", "secret")


async def test_login_cookie_and_signed_export():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/login":
            assert request.method == "POST"
            assert request.headers["origin"] == "https://urja-ops.flockenergy.tech"
            assert b"email=test%40example.invalid" in request.content
            return login_response()
        assert "session_token=one" in request.headers["cookie"]
        if request.url.path == "/portal/keys":
            return httpx.Response(200, json={"data": {"signingSecret": "secret"}})
        assert request.url.query == b"page=1"
        assert request.headers["x-signature"] == sign_request(
            "/portal/export", "page=1", request.headers["x-timestamp"], "secret"
        )
        return httpx.Response(200, json={"data": [], "total": 0})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        assert await client.export_meters() == {"data": [], "total": 0}
        assert paths == ["/login", "/portal/keys", "/portal/export"]
    finally:
        await client.close()


async def test_expired_session_renews_once_with_new_signing_key():
    logins = 0
    exports = 0
    keys = 0

    def handler(request):
        nonlocal logins, exports, keys
        if request.url.path == "/login":
            logins += 1
            return login_response(str(logins))
        if request.url.path == "/portal/keys":
            keys += 1
            return httpx.Response(200, json={"data": {"signingSecret": f"key-{logins}"}})
        exports += 1
        if exports == 1:
            return httpx.Response(401, json={"error": "signature_invalid"})
        assert request.headers["x-signature"] == sign_request(
            "/portal/export", "page=1", request.headers["x-timestamp"], "key-2"
        )
        assert "session_token=2" in request.headers["cookie"]
        return httpx.Response(200, json={"data": [], "total": 0})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        await client.export_meters()
        assert (logins, keys, exports) == (2, 2, 2)
    finally:
        await client.close()


async def test_auth_failure_is_bounded_and_sanitized():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/login":
            return login_response()
        return httpx.Response(401, json={"error": "bad", "secret": "do-not-leak"})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.readings("X")
        assert exc.value.code == "upstream_auth_failed"
        assert "do-not-leak" not in str(exc.value)
        assert calls.count("/login") == 2
        assert len(calls) == 4
    finally:
        await client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"type": "failure", "data": {"message": "bad password"}}),
        httpx.Response(200, json={"type": "redirect", "location": "/meters"}),
    ],
)
async def test_login_requires_success_and_session_cookie(response):
    client = PortalClient(live_settings(), httpx.MockTransport(lambda request: response))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.readings("X")
        assert exc.value.code == "upstream_auth_failed"
    finally:
        await client.close()


async def test_transient_retry_then_success(monkeypatch):
    calls = 0

    async def no_wait(seconds):
        pass

    monkeypatch.setattr("urja_api.portal.asyncio.sleep", no_wait)

    def handler(request):
        nonlocal calls
        if request.url.path == "/login":
            return login_response()
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        assert await client.readings("X") == {"data": []}
        assert calls == 3
    finally:
        await client.close()


async def test_retry_after_is_not_ignored():
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path == "/login":
            return login_response()
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.readings("X")
        assert exc.value.code == "upstream_rate_limited"
        assert calls == 1
    finally:
        await client.close()


@pytest.mark.parametrize("payload", ["<html>maintenance</html>", "[]"])
async def test_malformed_response(payload):
    def handler(request):
        return (
            login_response() if request.url.path == "/login" else httpx.Response(200, text=payload)
        )

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.readings("X")
        assert exc.value.code == "upstream_protocol_error"
    finally:
        await client.close()


async def test_transformer_pagination_checks_every_page():
    pages = []

    def handler(request):
        if request.url.path == "/login":
            return login_response()
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"data": [{"code": str(page)}], "total": 2, "page": page})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        assert await client.transformers() == [{"code": "1"}, {"code": "2"}]
        assert pages == [1, 2]
    finally:
        await client.close()


async def test_timeout_maps_to_gateway_timeout(monkeypatch):
    async def no_wait(seconds):
        pass

    monkeypatch.setattr("urja_api.portal.asyncio.sleep", no_wait)

    def handler(request):
        if request.url.path == "/login":
            return login_response()
        raise httpx.ReadTimeout("secret upstream details", request=request)

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.readings("X")
        assert exc.value.status == 504
        assert "secret" not in str(exc.value)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "key_payload", [{"data": None}, {"data": []}, {"data": {"signingSecret": ""}}]
)
async def test_invalid_key_payload_is_a_protocol_error(key_payload):
    def handler(request):
        if request.url.path == "/login":
            return login_response()
        return httpx.Response(200, json=key_payload)

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        with pytest.raises(ServiceError) as exc:
            await client.export_meters()
        assert exc.value.code == "upstream_protocol_error"
    finally:
        await client.close()


async def test_login_redirect_is_recovered_without_following_external_urls():
    reads = 0

    def handler(request):
        nonlocal reads
        if request.url.path == "/login":
            return login_response()
        reads += 1
        if reads == 1:
            return httpx.Response(302, headers={"location": "/login"})
        return httpx.Response(200, json={"data": []})

    client = PortalClient(live_settings(), httpx.MockTransport(handler))
    try:
        assert await client.readings("X") == {"data": []}
        assert reads == 2
    finally:
        await client.close()
