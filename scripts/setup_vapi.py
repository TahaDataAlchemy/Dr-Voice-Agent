"""
Create/update the Vapi assistant (custom-LLM -> this server) and attach a phone number.

    uv run python scripts/setup_vapi.py                     # uses PUBLIC_BASE_URL from .env
    uv run python scripts/setup_vapi.py --base-url https://xxxx.trycloudflare.com
    uv run python scripts/setup_vapi.py --no-number         # assistant only
    uv run python scripts/setup_vapi.py --print             # show the payload, do not call Vapi

Idempotent: re-running updates the same assistant (matched by VAPI_ASSISTANT_ID or name).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402
from modules.voice.assistant_config import build_assistant_payload  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", help="Public HTTPS origin of this server (defaults to PUBLIC_BASE_URL)")
    parser.add_argument("--no-number", action="store_true", help="Do not create/attach a phone number")
    parser.add_argument("--print", action="store_true", help="Print the assistant payload and exit")
    args = parser.parse_args()

    settings = get_settings()
    base_url = (args.base_url or settings.base_url or "").rstrip("/")
    if not base_url:
        print("error: pass --base-url or set PUBLIC_BASE_URL (Vapi must be able to reach this server over HTTPS)")
        return 2
    if args.print:
        print(json.dumps(build_assistant_payload(base_url), indent=2))
        return 0
    if not settings.vapi_api_key:
        print("error: VAPI_API_KEY is not set")
        return 2

    from modules.voice.vapi_setup import sync_assistant

    result = await sync_assistant(base_url, ensure_number=not args.no_number)
    print(json.dumps(result, indent=2))
    if result.get("phone_number"):
        print(f"\nCall {result['phone_number']} (it can take a few minutes for a new number to activate).")
    print("Tip: test without a phone from the Vapi dashboard -> Assistants -> 'Talk to assistant'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
