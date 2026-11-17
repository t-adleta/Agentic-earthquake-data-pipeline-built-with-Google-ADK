import json
from pathlib import Path

from quake_pipeline import processing, report

SAMPLE = json.loads(Path(__file__).with_name("sample_feed.geojson").read_text())


def test_region_from_place():
    assert processing.region_from_place("12 km SSW of Volcano, Hawaii") == "Hawaii"
    assert processing.region_from_place("8 km NE of Ridgecrest, CA") == "California"
    assert processing.region_from_place("south of the Fiji Islands") == "Fiji Islands"
    assert processing.region_from_place("Kermadec Islands region") == "Kermadec Islands region"
    assert processing.region_from_place(None) == "Unknown"


def test_clean_removes_bad_rows_and_filters():
    events, quality = processing.clean(processing.flatten(SAMPLE), min_magnitude=2.5)
    assert quality["rows_in"] == 123
    assert quality["dropped_duplicates"] == 1
    assert quality["dropped_non_earthquake"] == 1
    assert quality["dropped_missing_fields"] == 1
    assert (events["magnitude"] >= 2.5).all()
    assert events["id"].is_unique
    assert quality["rows_out"] == len(events) == 120 - quality["dropped_below_min_magnitude"]


def test_aggregate_totals_are_consistent():
    events, _ = processing.clean(processing.flatten(SAMPLE), min_magnitude=0)
    summary = processing.aggregate(events)
    total = summary["kpis"]["total_events"]
    assert total == 120
    assert sum(d["events"] for d in summary["daily"]) == total
    assert sum(d["events"] for d in summary["by_magnitude_class"]) == total
    assert sum(d["events"] for d in summary["by_depth_class"]) == total
    mags = [e["magnitude"] for e in summary["strongest_events"]]
    assert mags == sorted(mags, reverse=True)
    assert summary["kpis"]["max_magnitude"] == mags[0]


def test_empty_input_does_not_crash():
    events, _ = processing.clean(processing.flatten({"features": []}), 2.5)
    summary = processing.aggregate(events)
    assert summary["kpis"]["total_events"] == 0


def test_report_escapes_text():
    events, quality = processing.clean(processing.flatten(SAMPLE), 2.5)
    summary = processing.aggregate(events) | {"data_quality": quality, "run_id": "t", "period": "week", "min_magnitude": 2.5}
    page = report.build_html(json.loads(json.dumps(summary, default=str)), "<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in page
    assert "Earthquakes per day" in page
