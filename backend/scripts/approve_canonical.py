"""Promote a draft canonical answer to approved (the operator approval path).

The admin UI approval action lands in Phase V5; this CLI wires the same
``CanonicalAnswerRepository.approve`` transition so a draft staged via
``seed_canonical.py --status draft`` (or an import) can be served.

    uv run python scripts/approve_canonical.py --intent pricing
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

# Allow direct execution: add the backend root so `app` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.domain.canonical.repository import CanonicalAnswerRepository  # noqa: E402


async def approve(intent: str) -> bool:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        get_settings().mongo_uri.get_secret_value(), tz_aware=True
    )
    try:
        collection = client[get_settings().mongo_db_name]["canonical_answers"]
        return await CanonicalAnswerRepository(collection).approve(intent)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a draft canonical answer to approved.")
    parser.add_argument("--intent", required=True, help="The canonical intent to approve.")
    args = parser.parse_args()
    promoted = asyncio.run(approve(args.intent))
    if promoted:
        print(f"Approved canonical answer for intent {args.intent!r}.")
    else:
        print(f"No draft canonical answer found for intent {args.intent!r} (nothing to approve).")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
