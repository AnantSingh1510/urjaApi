import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from urja_api.app import create_app
from urja_api.config import Settings


def test_inventory_and_stable_pagination(client):
    first = client.get("/v1/meters?limit=5").json()
    second = client.get("/v1/meters?offset=5&limit=7").json()
    assert first["total"] == second["total"] == 12
    ids = [m["id"] for m in first["data"] + second["data"]]
    assert ids == sorted(set(ids)) and len(ids) == 12
    assert first["freshness"] == second["freshness"]
    assert first["freshness"]["source"] == "synthetic_demo"


def test_filters_apply_before_pagination(client):
    result = client.get(
        "/v1/meters", params={"make": "demo alpha", "status": "installed", "limit": 1}
    ).json()
    assert result["total"] == 3
    assert len(result["data"]) == 1
    assert result["data"][0]["id"] == "DEMO-001"
    assert client.get("/v1/meters?q=synth-0009").json()["data"][0]["id"] == "DEMO-009"
    assert client.get("/v1/meters?transformer_code=DEMO-DT1").json()["total"] == 4


def test_location_search(client):
    result = client.get(
        "/v1/meters", params={"latitude": 26.85, "longitude": 75.72, "radius_km": 0.01}
    ).json()
    assert result["total"] == 1
    assert result["data"][0]["id"] == "DEMO-001"
    assert result["data"][0]["distance_km"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "latitude=0",
        "latitude=0&longitude=0",
        "radius_km=1",
        "limit=0",
        "limit=201",
        "offset=-1",
        "latitude=91&longitude=0&radius_km=1",
        "latitude=NaN",
        "radius_km=inf",
    ],
)
def test_invalid_query_is_consistent_422(client, query):
    result = client.get("/v1/meters?" + query)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "invalid_input"
    assert result.headers["X-Request-ID"] == result.json()["error"]["request_id"]


def test_unknown_meter_and_route(client):
    assert client.get("/v1/meters/no-such-meter").status_code == 404
    assert client.get("/v1/meters/no-such-meter/readings").status_code == 404
    assert client.get("/nothing").json()["error"]["code"] == "http_error"


def test_reading_values_are_registers_and_deltas(client):
    result = client.get("/v1/meters/DEMO-001/readings").json()
    assert result["total"] == 48
    assert result["data"][0]["cumulative_kwh"] == 1000
    assert result["data"][0]["interval_kwh"] is None
    assert result["data"][1]["interval_kwh"] == 0.4
    assert result["valid_interval_kwh"] == 18.8
    assert result["valid_intervals"] == 47
    assert result["excluded_intervals"] == 0
    assert result["data"][0]["timestamp"].endswith("+05:30")


def test_reading_bounds_and_summary_before_pagination(client):
    result = client.get(
        "/v1/meters/DEMO-001/readings",
        params={
            "start": "2026-06-30T00:30:00+05:30",
            "end": "2026-06-30T01:30:00+05:30",
            "offset": 1,
            "limit": 1,
        },
    ).json()
    assert result["total"] == 3 and len(result["data"]) == 1
    assert result["valid_interval_kwh"] == 0.8
    assert result["data"][0]["interval_kwh"] == 0.4
    assert result["available_from"] == "2026-06-30T00:00:00+05:30"
    empty = client.get(
        "/v1/meters/DEMO-001/readings", params={"start": "2027-01-01T00:00:00Z"}
    ).json()
    assert empty["total"] == 0 and empty["valid_interval_kwh"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "start=2026-06-30T00:30:00",
        "start=banana",
        "limit=2001",
        "start=2027-01-01T00:00:00Z&end=2026-01-01T00:00:00Z",
    ],
)
def test_invalid_reading_bounds(client, query):
    assert client.get("/v1/meters/DEMO-001/readings?" + query).status_code == 422


def test_network_preserves_conflicts(client):
    data = client.get("/v1/network").json()
    dt = next(n for n in data["nodes"] if n["id"] == "dt:DEMO-DT3")
    assert len(dt["parent_ids"]) == 2
    assert len(dt["names"]) == 2
    codes = {i["code"] for i in data["issues"]}
    assert {
        "multiple_parents",
        "name_conflict",
        "missing_code",
        "transformer_feeder_conflict",
    } <= codes
    assert client.get("/v1/transformers").json()["total"] == 3


def test_auth_protects_data_but_not_liveness():
    config = Settings(demo=True, api_key="secret-key", _env_file=None)
    with TestClient(create_app(config)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/summary").status_code == 401
        assert client.get("/v1/summary", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/v1/summary", headers={"X-API-Key": "secret-key"}).status_code == 200


def test_schema_is_valid_and_checked_in():
    schema = create_app().openapi()
    validate(schema)
    path = Path(__file__).resolve().parents[1] / "openapi.json"
    assert json.loads(path.read_text()) == schema
    assert "APIKeyHeader" in schema["components"]["securitySchemes"]
    assert schema["paths"]["/v1/meters"]["get"]["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("ErrorResponse")
