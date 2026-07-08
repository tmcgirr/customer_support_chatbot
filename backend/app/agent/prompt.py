"""Versioned system-prompt loader.

Prompts live as markdown under ``app/agent/prompts/``. The active version is a
constant so prompt changes are explicit and reviewable (and gate the golden set).
"""

from functools import lru_cache
from pathlib import Path

CURRENT_PROMPT_VERSION = "sys-v1"

_PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_system_prompt(version: str = CURRENT_PROMPT_VERSION) -> str:
    return (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
