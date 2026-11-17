"""Transformation logic: clean the raw USGS GeoJSON and aggregate it.

Pure functions with no ADK or cloud dependencies, so they are easy to test.
"""
from __future__ import annotations

import pandas as pd

MAG_BINS = [-10, 2, 4, 5, 6, 7, 20]
MAG_LABELS = ["Micro (<2)", "Minor (2-3.9)", "Light (4-4.9)",
              "Moderate (5-5.9)", "Strong (6-6.9)", "Major (7+)"]
DEPTH_BINS = [-1000, 70, 300, 1000]
DEPTH_LABELS = ["Shallow (<70 km)", "Intermediate (70-300 km)", "Deep (>300 km)"]
REGION_ALIASES = {"CA": "California", "NV": "Nevada", "MX": "Mexico"}


def flatten(geojson: dict) -> pd.DataFrame:
    """Turn the nested GeoJSON features into one flat row per event."""
    rows = []
    for f in geojson.get("features", []):
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        rows.append({
            "id": f.get("id"),
            "time_ms": p.get("time"),
            "magnitude": p.get("mag"),
            "place": p.get("place"),
            "event_type": p.get("type"),
            "significance": p.get("sig"),
            "tsunami_flag": p.get("tsunami"),
            "longitude": coords[0],
            "latitude": coords[1],
            "depth_km": coords[2],
        })
    cols = ["id", "time_ms", "magnitude", "place", "event_type", "significance",
            "tsunami_flag", "longitude", "latitude", "depth_km"]
    return pd.DataFrame(rows, columns=cols)


def region_from_place(place: str | None) -> str:
    """'12 km SSW of Volcano, Hawaii' -> 'Hawaii'; 'Fiji region' -> 'Fiji region'."""
    if not place:
        return "Unknown"
    region = place.rsplit(", ", 1)[-1].strip()
    if " of " in region:  # e.g. 'south of the Kermadec Islands'
        region = region.split(" of ", 1)[1].strip()
    if region.lower().startswith("the "):
        region = region[4:]
    return REGION_ALIASES.get(region, region) or "Unknown"


def clean(df: pd.DataFrame, min_magnitude: float) -> tuple[pd.DataFrame, dict]:
    """Filter and enrich events. Returns the clean table and a data-quality log."""
    quality = {"rows_in": len(df)}

    before = len(df)
    df = df.drop_duplicates(subset="id")
    quality["dropped_duplicates"] = before - len(df)

    before = len(df)
    df = df[df["event_type"] == "earthquake"]  # removes quarry blasts, explosions...
    quality["dropped_non_earthquake"] = before - len(df)

    before = len(df)
    df = df.dropna(subset=["magnitude", "time_ms", "latitude", "longitude"])
    quality["dropped_missing_fields"] = before - len(df)

    before = len(df)
    df = df[df["magnitude"] >= min_magnitude].copy()
    quality["dropped_below_min_magnitude"] = before - len(df)
    quality["rows_out"] = len(df)

    df["time_utc"] = pd.to_datetime(df["time_ms"], unit="ms", utc=True)
    df["date"] = df["time_utc"].dt.strftime("%Y-%m-%d")
    df["region"] = df["place"].map(region_from_place)
    df["magnitude_class"] = pd.cut(df["magnitude"], MAG_BINS, labels=MAG_LABELS, right=False)
    df["depth_class"] = pd.cut(df["depth_km"], DEPTH_BINS, labels=DEPTH_LABELS, right=False)
    df = df.drop(columns=["time_ms"]).sort_values("time_utc")
    return df, quality


def aggregate(df: pd.DataFrame, top_n: int = 10) -> dict:
    """Group the clean events into the tables the report shows."""
    if df.empty:
        return {"kpis": {"total_events": 0}, "daily": [], "by_magnitude_class": [],
                "by_depth_class": [], "top_regions": [], "strongest_events": []}

    daily = (df.groupby("date")
               .agg(events=("id", "count"), max_magnitude=("magnitude", "max"),
                    avg_magnitude=("magnitude", "mean"))
               .round(2).reset_index())

    by_mag = (df.groupby("magnitude_class", observed=False)
                .agg(events=("id", "count")).reset_index())
    by_mag["share_pct"] = (100 * by_mag["events"] / len(df)).round(1)

    by_depth = (df.groupby("depth_class", observed=False)
                  .agg(events=("id", "count"), avg_magnitude=("magnitude", "mean"))
                  .round(2).fillna(0).reset_index())

    regions = (df.groupby("region")
                 .agg(events=("id", "count"), avg_magnitude=("magnitude", "mean"),
                      max_magnitude=("magnitude", "max"), avg_depth_km=("depth_km", "mean"))
                 .round(2)
                 .sort_values(["events", "max_magnitude"], ascending=False)
                 .head(top_n).reset_index())

    strongest = (df.sort_values("magnitude", ascending=False).head(top_n)
                   [["time_utc", "magnitude", "place", "depth_km", "tsunami_flag"]].copy())
    strongest["time_utc"] = strongest["time_utc"].dt.strftime("%Y-%m-%d %H:%M UTC")

    busiest = daily.loc[daily["events"].idxmax()]
    top = df.loc[df["magnitude"].idxmax()]
    kpis = {
        "total_events": int(len(df)),
        "date_range": f"{df['date'].min()} to {df['date'].max()}",
        "avg_magnitude": round(float(df["magnitude"].mean()), 2),
        "max_magnitude": float(top["magnitude"]),
        "strongest_event_place": top["place"],
        "events_m5_plus": int((df["magnitude"] >= 5).sum()),
        "tsunami_flagged": int((df["tsunami_flag"] == 1).sum()),
        "regions_affected": int(df["region"].nunique()),
        "busiest_day": busiest["date"],
        "busiest_day_events": int(busiest["events"]),
    }
    as_records = lambda t: t.astype(object).to_dict(orient="records")
    return {
        "kpis": kpis,
        "daily": as_records(daily),
        "by_magnitude_class": as_records(by_mag),
        "by_depth_class": as_records(by_depth),
        "top_regions": as_records(regions),
        "strongest_events": as_records(strongest),
    }
