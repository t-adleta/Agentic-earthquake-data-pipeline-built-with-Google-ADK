"""Agent definitions. `root_agent` is what `adk run` / `adk web` load.

A SequentialAgent runs four specialist LLM agents in a fixed order. Each one owns
one stage of the pipeline, decides how to call its tool from the user's request,
checks the result, and reports it. Stages share file paths through session state.
"""
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models import Gemini
from google.genai import types

from . import config
from .tools import build_report, fetch_earthquakes, transform_earthquakes, upload_data_to_cloud

# Wait and retry when Gemini is rate-limited (429, e.g. free-tier 5 requests/minute)
# or temporarily overloaded (503/504), instead of failing the whole run.
MODEL = Gemini(
    model=config.MODEL,
    retry_options=types.HttpRetryOptions(
        attempts=6, initial_delay=10, max_delay=65, exp_base=2,
        http_status_codes=[429, 500, 503, 504]),
)

ON_ERROR = (" If the tool returns status 'error', state the error message plainly and do not "
            "retry more than once.")

ingestion_agent = LlmAgent(
    name="ingestion_agent",
    model=MODEL,
    description="Pulls raw earthquake data from the USGS public API.",
    instruction=(
        "You are the ingestion stage of a data pipeline. Call fetch_earthquakes exactly once. "
        "Choose `period` from the user's request: 'day', 'week' or 'month'. If the user does "
        "not say, use 'week'. Then report in one sentence how many raw events were fetched."
        + ON_ERROR),
    tools=[fetch_earthquakes],
    output_key="ingestion_result",
)

transform_agent = LlmAgent(
    name="transform_agent",
    model=MODEL,
    description="Cleans, filters and aggregates the raw data.",
    instruction=(
        "You are the transformation stage. Call transform_earthquakes exactly once. Choose "
        "`min_magnitude` from the user's request; if the user gives none, use 2.5 (roughly the "
        "smallest quake people feel). Then report in two sentences: the headline KPIs, and how "
        "many rows the data-quality checks removed and why."
        + ON_ERROR),
    tools=[transform_earthquakes],
    output_key="transform_result",
)

storage_agent = LlmAgent(
    name="storage_agent",
    model=MODEL,
    description="Saves raw and processed data to cloud object storage.",
    instruction=(
        "You are the storage stage. Call upload_data_to_cloud exactly once, then list the "
        "cloud URIs that were written. If the status is 'skipped', say that uploads were "
        "skipped and why."
        + ON_ERROR),
    tools=[upload_data_to_cloud],
    output_key="storage_result",
)

report_agent = LlmAgent(
    name="report_agent",
    model=MODEL,
    description="Interprets the results and publishes the HTML report.",
    instruction=(
        "You are the reporting stage and a careful data analyst. Here is the processed "
        "summary as JSON:\n{summary_digest?}\n\n"
        "First write `insights`: 3 to 4 plain-English sentences on what stands out (overall "
        "activity, the strongest event, the most active regions, magnitude and depth mix). "
        "Use only numbers that appear in the summary. Then call build_report exactly once with "
        "that text. Finish by telling the user where the report was saved."
        + ON_ERROR),
    tools=[build_report],
    output_key="report_result",
)

root_agent = SequentialAgent(
    name="quake_pipeline",
    description="Ingest -> transform -> store -> visualize pipeline for USGS earthquake data.",
    sub_agents=[ingestion_agent, transform_agent, storage_agent, report_agent],
)
