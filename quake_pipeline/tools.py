"""The tools the agents call. Each tool does one pipeline step.

Large data never passes through the LLM: tools write files and hand the *paths*
to the next step through ADK session state (tool_context.state). Only small
summaries are returned to the model.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from google.adk.tools import ToolContext

from . import config, processing, report, storage


def fetch_earthquakes(period: str, tool_context: ToolContext) -> dict:
    """Downloads recent earthquakes from the public USGS API and saves the raw file.

    Args:
        period: How far back to pull data. One of "day", "week" or "month".

    Returns:
        A dict with status, the number of raw events and where the raw file was saved.
    """
    period = (period or "week").lower().strip()
    if period not in config.VALID_PERIODS:
        return {"status": "error", "message": f"period must be one of {config.VALID_PERIODS}"}

    url = config.USGS_FEED.format(period=period)
    last_error = None
    for attempt in range(3):  # simple retry with backoff for a flaky network
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))
    else:
        return {"status": "error", "message": f"USGS API request failed: {last_error}"}

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = config.DATA_DIR / "raw" / f"earthquakes_{period}_{run_id}.geojson"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(data))

    tool_context.state["run_id"] = run_id
    tool_context.state["period"] = period
    tool_context.state["raw_path"] = str(raw_path)
    return {"status": "success", "source_url": url, "raw_events": len(data.get("features", [])),
            "raw_path": str(raw_path), "run_id": run_id}


def transform_earthquakes(min_magnitude: float, tool_context: ToolContext) -> dict:
    """Cleans the raw earthquake file and aggregates it by day, magnitude, depth and region.

    Args:
        min_magnitude: Drop events weaker than this magnitude (for example 2.5). Use 0 to keep all.

    Returns:
        A dict with status, headline KPIs, the data-quality log and output file paths.
    """
    raw_path = tool_context.state.get("raw_path")
    if not raw_path or not Path(raw_path).exists():
        return {"status": "error", "message": "No raw file found. The ingestion step must run first."}

    run_id = tool_context.state["run_id"]
    geojson = json.loads(Path(raw_path).read_text())
    events, quality = processing.clean(processing.flatten(geojson), float(min_magnitude))
    summary = processing.aggregate(events)
    summary.update({"run_id": run_id, "period": tool_context.state.get("period"),
                    "min_magnitude": float(min_magnitude), "data_quality": quality})

    out_dir = config.DATA_DIR / "processed" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path, summary_path = out_dir / "events_clean.csv", out_dir / "summary.json"
    events.to_csv(events_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    # A compact version for the reporting agent's prompt (kept small on purpose).
    digest = {"kpis": summary["kpis"], "top_regions": summary["top_regions"][:5],
              "by_magnitude_class": summary["by_magnitude_class"],
              "by_depth_class": summary["by_depth_class"]}
    tool_context.state["events_path"] = str(events_path)
    tool_context.state["summary_path"] = str(summary_path)
    tool_context.state["summary_digest"] = json.dumps(digest, default=str)
    return {"status": "success", "kpis": summary["kpis"], "data_quality": quality,
            "events_path": str(events_path), "summary_path": str(summary_path)}


def upload_data_to_cloud(tool_context: ToolContext) -> dict:
    """Uploads the raw file and the processed files to the cloud storage bucket.

    Returns:
        A dict with status and the cloud URIs of the uploaded objects.
    """
    state = tool_context.state
    run_id = state.get("run_id")
    files = {
        f"raw/{run_id}/earthquakes.geojson": state.get("raw_path"),
        f"processed/{run_id}/events_clean.csv": state.get("events_path"),
        f"processed/{run_id}/summary.json": state.get("summary_path"),
    }
    if not all(files.values()):
        return {"status": "error", "message": "Raw or processed files are missing. Run ingestion and transformation first."}
    if not config.BUCKET_NAME:
        return {"status": "skipped", "message": "BUCKET_NAME is not set, so nothing was uploaded. Files remain on local disk."}
    try:
        uris = [storage.upload_file(Path(path), key) for key, path in files.items()]
    except Exception as exc:  # auth, permissions, missing bucket...
        return {"status": "error", "message": f"Cloud upload failed: {exc}"}
    state["uploaded_uris"] = uris
    return {"status": "success", "backend": config.STORAGE_BACKEND, "uploaded": uris}


def build_report(insights: str, tool_context: ToolContext) -> dict:
    """Builds the HTML web page with charts and tables, and uploads it to the bucket.

    Args:
        insights: A short plain-English paragraph of key findings to show at the top of the page.

    Returns:
        A dict with status, the local path of the HTML page and its cloud URI if uploaded.
    """
    summary_path = tool_context.state.get("summary_path")
    if not summary_path or not Path(summary_path).exists():
        return {"status": "error", "message": "No processed summary found. The transformation step must run first."}

    summary = json.loads(Path(summary_path).read_text())
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = config.OUTPUT_DIR / "report.html"
    report_path.write_text(report.build_html(summary, insights), encoding="utf-8")

    result = {"status": "success", "report_path": str(report_path.resolve())}
    if config.BUCKET_NAME:
        try:
            result["report_uri"] = storage.upload_file(report_path, f"reports/{summary['run_id']}/report.html")
            # Assign a new list (not append in place) so ADK records the state change.
            tool_context.state["uploaded_uris"] = [*tool_context.state.get("uploaded_uris", []),
                                                   result["report_uri"]]
        except Exception as exc:
            result["upload_warning"] = f"Report built locally but upload failed: {exc}"
    tool_context.state["report_path"] = result["report_path"]
    return result
