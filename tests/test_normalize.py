import pytest

from urja_api.errors import ServiceError
from urja_api.models import Geo
from urja_api.normalize import distance_km, meter_from_export, normalize_readings, with_intervals


def raw_reading(timestamp, kwh="1"):
    return {"timestamp": timestamp, "kwh": kwh, "kvah": "1.1", "voltR": "230"}


def normalize(rows):
    return with_intervals(normalize_readings({"data": rows}, "Asia/Kolkata"))


def test_zero_is_a_real_value():
    rows = normalize([raw_reading("30/06/2026 00:00", "0"), raw_reading("30/06/2026 00:30", "0")])
    assert rows[0].cumulative_kwh == 0
    assert rows[1].interval_kwh == 0
    assert not rows[0].issues


def test_reset_gap_missing_and_invalid_timestamp_are_not_fabricated():
    rows = normalize(
        [
            raw_reading("30/06/2026 00:00", "10"),
            raw_reading("30/06/2026 00:30", "2"),
            raw_reading("30/06/2026 02:00", "3"),
            raw_reading("30/06/2026 02:30", ""),
            raw_reading("bad-time", "4"),
        ]
    )
    assert all(r.interval_kwh is None for r in rows)
    assert rows[-1].timestamp is None
    assert {"register_reset", "reading_gap", "invalid_reading_value", "invalid_timestamp"} <= {
        i.code for r in rows for i in r.issues
    }


def test_duplicates_are_retained_without_double_counting():
    rows = normalize(
        [
            raw_reading("30/06/2026 00:30", "2"),
            raw_reading("30/06/2026 00:00", "1"),
            raw_reading("30/06/2026 00:30", "2"),
            raw_reading("30/06/2026 01:00", "3"),
            raw_reading("30/06/2026 01:30", "4"),
        ]
    )
    assert len(rows) == 5
    assert [r.interval_kwh for r in rows] == [None, None, None, None, 1]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "—", True, None])
def test_invalid_numeric_values_become_null_with_issue(value):
    row = normalize([raw_reading("30/06/2026 00:00", value)])[0]
    assert row.cumulative_kwh is None
    assert row.issues[0].code == "invalid_reading_value"


async def test_missing_codes_and_invalid_geo(portal):
    row = (await portal.export_meters())["data"][10]
    row["geo"] = {"lat": 100, "lng": 75}
    meter = meter_from_export(row)
    assert meter.location is None
    assert meter.hierarchy[1].code is None
    assert {i.code for i in meter.issues} == {"invalid_location", "missing_hierarchy_code"}


def test_changed_export_schema_fails_loudly():
    with pytest.raises(ServiceError):
        meter_from_export({"meterId": "one"})


def test_haversine_handles_antipodes_and_zero():
    a = Geo(latitude=0, longitude=0)
    assert distance_km(a, a) == 0
    assert distance_km(a, Geo(latitude=0, longitude=180)) == pytest.approx(20015.114, abs=0.001)


def test_interval_calculation_does_not_mutate_cache():
    original = normalize_readings(
        {"data": [raw_reading("30/06/2026 00:00"), raw_reading("30/06/2026 00:30", "2")]},
        "Asia/Kolkata",
    )
    assert with_intervals(original)[1].interval_kwh == 1
    assert original[1].interval_kwh is None
