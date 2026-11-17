"""Runs the real ADK agent graph end to end with no network and no API keys.

The Gemini model is replaced by a scripted stand-in that makes the same tool
calls a real model would, and the USGS request is served from a local sample
file. This checks the agent wiring, state hand-offs and tools together.
"""
import asyncio
import json
from pathlib import Path

from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

SAMPLE = Path(__file__).with_name("sample_feed.geojson")
SCRIPTED_ARGS = {
    "fetch_earthquakes": {"period": "week"},
    "transform_earthquakes": {"min_magnitude": 2.5},
    "upload_data_to_cloud": {},
    "build_report": {"insights": "Scripted insight text for the offline test."},
}


class ScriptedLlm(BaseLlm):
    """Calls the agent's single tool once, then replies with text."""

    async def generate_content_async(self, llm_request, stream=False):
        tool = next(d.name for t in llm_request.config.tools for d in t.function_declarations)
        last = llm_request.contents[-1]
        if any(p.function_response for p in last.parts):
            part = types.Part(text=f"{tool} finished.")
        else:
            part = types.Part(function_call=types.FunctionCall(name=tool, args=SCRIPTED_ARGS[tool]))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class FakeResponse:
    def raise_for_status(self): pass
    def json(self): return json.loads(SAMPLE.read_text())


def test_full_pipeline_offline(tmp_path, monkeypatch):
    from quake_pipeline import config, storage, tools
    from quake_pipeline.agent import root_agent

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(tools.requests, "get", lambda url, timeout: FakeResponse())
    uploaded = []
    monkeypatch.setattr(storage, "upload_file", lambda path, key: uploaded.append(key) or f"gs://test-bucket/{key}")
    for agent in root_agent.sub_agents:
        monkeypatch.setattr(agent, "model", ScriptedLlm(model="scripted"))

    async def run():
        runner = InMemoryRunner(agent=root_agent, app_name="t")
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        msg = types.Content(role="user", parts=[types.Part(text="Run the pipeline")])
        authors = [e.author async for e in runner.run_async(user_id="u", session_id=session.id, new_message=msg)]
        final = await runner.session_service.get_session(app_name="t", user_id="u", session_id=session.id)
        return authors, final.state

    authors, state = asyncio.run(run())

    order = list(dict.fromkeys(authors))
    assert order == ["ingestion_agent", "transform_agent", "storage_agent", "report_agent"]
    assert len(uploaded) == 4  # raw, clean events, summary, report
    assert any(k.startswith("raw/") for k in uploaded) and any(k.startswith("reports/") for k in uploaded)
    summary = json.loads(Path(state["summary_path"]).read_text())
    assert summary["kpis"]["total_events"] > 0
    html = Path(state["report_path"]).read_text()
    assert "Scripted insight text" in html and "Most active regions" in html
