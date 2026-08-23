"""
Talk to the registration agent in your terminal (same LangChain loop Vapi uses, minus the voice).

    uv run python scripts/chat.py                 # needs OPENROUTER_API_KEY
    uv run python scripts/chat.py --caller +14155550139

Useful for iterating on the prompt and tools without spending Vapi minutes. The conversation is stored
like a real call (channel=web, vapi_call_id=terminal-<n>) so it shows up in the dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from config import get_settings  # noqa: E402
from modules.voice.agent import VoiceAgent  # noqa: E402
from modules.voice.context import CallContext  # noqa: E402
from modules.voice.prompt import first_message  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--caller", default=None, help="Caller id to simulate, e.g. +14155550139")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY is not set - the agent cannot talk without an LLM.")
        return 2

    from core.server import init_database, seed_database

    init_database()
    seed_database()

    agent = VoiceAgent()
    call_id = f"terminal-{uuid.uuid4().hex[:8]}"
    ctx = CallContext(vapi_call_id=call_id, caller_number=args.caller, channel="web")
    history = [AIMessage(content=first_message())]
    print(f"\n[call {call_id}]  model={settings.llm_model}\n")
    print(f"Sam: {first_message()}")

    while not ctx.end_call_requested:
        try:
            user = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(bye)")
            return 0
        if not user:
            continue
        history.append(HumanMessage(content=user))
        ctx.turn_index = len(history)
        print("Sam: ", end="", flush=True)
        reply = []
        async for event in agent.run_turn(ctx, history):
            if event.type in ("text", "error"):
                print(event.content, end="", flush=True)
                reply.append(event.content)
            elif event.type == "tool_call":
                print(f"\n   [tool {event.name} {event.data}]", flush=True)
                print("Sam: ", end="", flush=True)
            elif event.type == "end_call":
                print("\n   [call ended]")
        print()
        history.append(AIMessage(content="".join(reply)))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
