"""Run the whole pipeline from the command line.

    python run_pipeline.py
    python run_pipeline.py "Run the pipeline for the past month, magnitude 4.5 and up"
"""
import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from quake_pipeline.agent import root_agent

DEFAULT_REQUEST = "Run the earthquake pipeline for the past week with a minimum magnitude of 2.5."


async def main(request: str) -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="quake_pipeline")
    session = await runner.session_service.create_session(app_name="quake_pipeline", user_id="local")
    message = types.Content(role="user", parts=[types.Part(text=request)])

    print(f"Request: {request}\n")
    async for event in runner.run_async(user_id="local", session_id=session.id, new_message=message):
        for part in (event.content.parts if event.content else []) or []:
            if part.function_call:
                print(f"[{event.author}] calling {part.function_call.name}({dict(part.function_call.args)})")
            elif part.text and not getattr(part, "thought", False):
                print(f"[{event.author}] {part.text.strip()}\n")

    final = await runner.session_service.get_session(
        app_name="quake_pipeline", user_id="local", session_id=session.id)
    print("Report:", final.state.get("report_path", "not created"))
    for uri in final.state.get("uploaded_uris", []):
        print("Uploaded:", uri)


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or DEFAULT_REQUEST))
