"""Model-provider selection.

Which provider answers a turn is a runtime toggle (admin portal), persisted in
``app_settings`` and read by BOTH the API and the worker. This module centralizes:
which providers are configured (have a key), how to build each adapter, and a small
TTL-cached resolver so a switch takes effect within seconds in every process without a
Mongo read on every turn. Provider-specific types still live only in ``adapter.py``.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.agent.adapter import (
    AnthropicMessagesAdapter,
    ModelAdapter,
    OpenAIResponsesAdapter,
    UsageHook,
)
from app.core.config import Settings
from app.domain.settings.models import Provider
from app.domain.settings.repository import SettingsRepository

_ALL_PROVIDERS: tuple[Provider, ...] = ("openai", "anthropic", "openrouter")


def _has_key(settings: Settings, provider: Provider) -> bool:
    if provider == "openai":
        return bool(settings.openai_api_key.get_secret_value())
    if provider == "anthropic":
        return bool(settings.anthropic_api_key.get_secret_value())
    return bool(settings.openrouter_api_key.get_secret_value())


def available_providers(settings: Settings) -> list[Provider]:
    """Providers with a usable key configured — the only ones the admin toggle may select."""
    return [p for p in _ALL_PROVIDERS if _has_key(settings, p)]


def _build_one(provider: Provider, settings: Settings, on_usage: UsageHook | None) -> ModelAdapter:
    if provider == "anthropic":
        return AnthropicMessagesAdapter(on_usage=on_usage)
    if provider == "openrouter":
        # OpenRouter speaks the OpenAI Responses API — reuse that adapter with a base_url
        # override + a non-native model id; embeddings still route to real OpenAI.
        return OpenAIResponsesAdapter(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            model=settings.openrouter_model,
            on_usage=on_usage,
        )
    return OpenAIResponsesAdapter(on_usage=on_usage)


def build_adapters(
    settings: Settings, on_usage: UsageHook | None = None
) -> dict[Provider, ModelAdapter]:
    """Build one adapter per relevant provider, reused for the process lifetime.

    The startup-default provider is ALWAYS built (so the app boots and the chat path
    degrades to MODEL_UNAVAILABLE rather than crashing when a key is missing in dev,
    matching the pre-multi-provider behavior); the other provider is built only when its
    key is configured (so it is genuinely selectable). ``on_usage`` is the classify/embed
    usage sink (records to the llm_usage rollup); passed through to every adapter."""
    default = settings.model_provider
    adapters: dict[Provider, ModelAdapter] = {default: _build_one(default, settings, on_usage)}
    for provider in _ALL_PROVIDERS:
        if provider not in adapters and _has_key(settings, provider):
            adapters[provider] = _build_one(provider, settings, on_usage)
    return adapters


@dataclass(frozen=True)
class ModelProviders:
    """What the admin panel needs to render the toggle — the startup default and the set
    of key-configured providers that can be selected. No secrets."""

    default: Provider
    available: list[Provider]


def model_providers(settings: Settings) -> ModelProviders:
    return ModelProviders(default=settings.model_provider, available=available_providers(settings))


class ProviderResolver:
    """Resolves the active adapter from the runtime setting, TTL-cached to avoid a Mongo
    read on every turn. ``invalidate()`` gives the admin write path a write-through refresh
    so a switch is instant in the API process (other processes catch up within the TTL)."""

    def __init__(
        self,
        adapters: dict[Provider, ModelAdapter],
        repo: SettingsRepository,
        *,
        default: Provider,
        ttl_seconds: float = 10.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapters = adapters
        self._repo = repo
        self._default = default
        self._ttl = ttl_seconds
        self._now = now
        self._cached: Provider | None = None
        self._cached_at = 0.0

    def invalidate(self) -> None:
        self._cached = None

    async def active_provider(self) -> Provider:
        now = self._now()
        if self._cached is not None and now - self._cached_at < self._ttl:
            return self._cached
        provider = await self._repo.get_active_provider()
        self._cached = provider
        self._cached_at = now
        return provider

    async def resolve(self) -> ModelAdapter:
        provider = await self.active_provider()
        adapter = self._adapters.get(provider)
        if adapter is not None:
            return adapter
        # The selected provider isn't built (key removed, or never configured). Fail SAFE
        # to the startup default so a chat turn never bricks on a stale/invalid selection.
        return self._adapters.get(self._default) or next(iter(self._adapters.values()))

    async def aclose(self) -> None:
        # aclose is not on the ModelAdapter protocol (fakes don't implement it); close
        # defensively, matching how main.py closes the knowledge store.
        for adapter in self._adapters.values():
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                await closer()
