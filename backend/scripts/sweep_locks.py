"""Release leaked conversation run-locks (operational cleanup, Phase 8).

The send path recovers a stale lock opportunistically, but a conversation that
is never messaged again keeps its leaked lock. This global sweep clears every
run lock older than ``lock_stale_seconds`` (or ``--older-than SECONDS``). Safe to
run on a cron; a legitimately in-flight turn has a young lock and is untouched.

    uv run python scripts/sweep_locks.py
    uv run python scripts/sweep_locks.py --older-than 300
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

# Allow direct execution: add the backend root so `app` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.domain.conversations.repository import ConversationRepository  # noqa: E402

logger = get_logger("scripts.sweep_locks")


async def sweep(older_than_seconds: int) -> int:
    settings = get_settings()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        settings.mongo_uri.get_secret_value(), tz_aware=True
    )
    try:
        repo = ConversationRepository(client[settings.mongo_db_name]["conversations"])
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        cleared = await repo.clear_stale_locks(cutoff)
        logger.info(
            "locks.swept",
            extra={"context": {"cleared": cleared, "older_than_seconds": older_than_seconds}},
        )
        return cleared
    finally:
        client.close()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Release leaked conversation run-locks.")
    parser.add_argument(
        "--older-than",
        type=int,
        default=get_settings().lock_stale_seconds,
        help="Clear locks whose run started more than SECONDS ago.",
    )
    args = parser.parse_args()
    cleared = asyncio.run(sweep(args.older_than))
    print(f"Cleared {cleared} stale lock(s) older than {args.older_than}s.")


if __name__ == "__main__":
    main()
