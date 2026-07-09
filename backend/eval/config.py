"""Named evaluation configurations — a config is the set of knobs a dev/test engineer
A-Bs when judging chatbot performance + routing: which MODEL answers, the FALLBACK model,
and which system-prompt VERSION (routing behaviour lives in the prompt + tools).

This is standalone developer tooling — it never runs in the request path or the admin app.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.agent.prompt import CURRENT_PROMPT_VERSION
from app.core.config import get_settings


@dataclass(frozen=True)
class EvalConfig:
    name: str
    model: str
    provider: str = "openai"  # which adapter answers: "openai" | "anthropic"
    fallback_model: str | None = None
    prompt_version: str = CURRENT_PROMPT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "fallback_model": self.fallback_model,
            "prompt_version": self.prompt_version,
        }


def current_config() -> EvalConfig:
    """The config that ships today (from settings) — the gate baseline for whichever
    provider is the env default."""
    settings = get_settings()
    if settings.model_provider == "anthropic":
        model = settings.anthropic_model
        fallback = settings.anthropic_fallback_model or None
    elif settings.model_provider == "openrouter":
        model = settings.openrouter_model
        fallback = None  # OpenRouter has no separate fallback model configured
    else:
        model = settings.openai_model
        fallback = settings.openai_fallback_model or None
    return EvalConfig(
        name="current",
        provider=settings.model_provider,
        model=model,
        fallback_model=fallback,
        prompt_version=CURRENT_PROMPT_VERSION,
    )


def load_configs(path: Path) -> list[EvalConfig]:
    """Load a list of named configs to compare from a YAML file (see configs.example.yaml)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError("configs file must be a YAML list of {name, model, ...} entries")
    configs: list[EvalConfig] = []
    for entry in data:
        configs.append(
            EvalConfig(
                name=str(entry["name"]),
                provider=str(entry.get("provider", "openai")),
                model=str(entry["model"]),
                fallback_model=(
                    str(entry["fallback_model"]) if entry.get("fallback_model") else None
                ),
                prompt_version=str(entry.get("prompt_version", CURRENT_PROMPT_VERSION)),
            )
        )
    names = [c.name for c in configs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"config names must be unique — duplicated: {', '.join(dupes)}")
    return configs
