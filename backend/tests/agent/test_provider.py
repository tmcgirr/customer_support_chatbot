"""Provider registry + resolver: which adapter answers, and the TTL cache."""

from typing import Any

from app.agent.provider import ProviderResolver, available_providers, build_adapters
from app.core.config import Settings
from app.domain.settings.models import Provider


class _FakeSettingsRepo:
    """Stands in for SettingsRepository; counts reads so the TTL cache is observable."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        self.reads = 0

    async def get_active_provider(self) -> Provider:
        self.reads += 1
        return self.provider


def _resolver(
    adapters: dict[Provider, Any], repo: _FakeSettingsRepo, clock: list[float]
) -> ProviderResolver:
    return ProviderResolver(
        adapters,
        repo,  # type: ignore[arg-type]
        default="openai",
        ttl_seconds=10.0,
        now=lambda: clock[0],
    )


async def test_resolve_returns_the_active_provider_adapter() -> None:
    openai_a, anthropic_a = object(), object()
    repo = _FakeSettingsRepo("anthropic")
    resolver = _resolver({"openai": openai_a, "anthropic": anthropic_a}, repo, [0.0])
    assert await resolver.resolve() is anthropic_a


async def test_ttl_caches_then_refreshes() -> None:
    openai_a, anthropic_a = object(), object()
    repo = _FakeSettingsRepo("openai")
    clock = [0.0]
    resolver = _resolver({"openai": openai_a, "anthropic": anthropic_a}, repo, clock)

    assert await resolver.resolve() is openai_a
    assert repo.reads == 1

    # Underlying provider changes, but within the TTL the cached value is served.
    repo.provider = "anthropic"
    clock[0] = 5.0
    assert await resolver.resolve() is openai_a
    assert repo.reads == 1

    # Past the TTL it re-reads and picks up the switch.
    clock[0] = 11.0
    assert await resolver.resolve() is anthropic_a
    assert repo.reads == 2


async def test_invalidate_forces_a_reread() -> None:
    openai_a, anthropic_a = object(), object()
    repo = _FakeSettingsRepo("openai")
    resolver = _resolver({"openai": openai_a, "anthropic": anthropic_a}, repo, [0.0])

    assert await resolver.resolve() is openai_a
    repo.provider = "anthropic"
    resolver.invalidate()  # write-through after an admin switch
    assert await resolver.resolve() is anthropic_a


async def test_resolve_falls_back_to_default_when_active_not_built() -> None:
    # A stale/invalid selection (provider not built) must never brick a turn.
    openai_a = object()
    repo = _FakeSettingsRepo("anthropic")
    resolver = _resolver({"openai": openai_a}, repo, [0.0])
    assert await resolver.resolve() is openai_a


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "dev",
        "model_provider": "openai",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "openrouter_api_key": "",
    }
    base.update(over)
    # _env_file=None so the local .env's provider keys never leak into these assertions.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_available_providers_reflects_configured_keys() -> None:
    assert available_providers(_settings(openai_api_key="sk-x")) == ["openai"]
    assert available_providers(_settings(openai_api_key="sk-x", anthropic_api_key="sk-y")) == [
        "openai",
        "anthropic",
    ]
    assert available_providers(_settings()) == []


def test_build_adapters_always_builds_the_default_plus_configured() -> None:
    # Both keys set → both built.
    both = build_adapters(_settings(openai_api_key="sk-x", anthropic_api_key="sk-y"))
    assert set(both) == {"openai", "anthropic"}
    # Only the default's key → just the default.
    only_default = build_adapters(_settings(openai_api_key="sk-x"))
    assert set(only_default) == {"openai"}
    # Default is anthropic with no keys → still built (so the app boots; fails at call time).
    default_anthropic = build_adapters(_settings(model_provider="anthropic"))
    assert set(default_anthropic) == {"anthropic"}


def test_openrouter_is_available_and_built_when_keyed() -> None:
    # OpenRouter is a third selectable provider once its key is set; it reuses the OpenAI
    # Responses adapter under the hood, but the registry treats it as a distinct provider.
    s = _settings(openai_api_key="sk-x", openrouter_api_key="sk-or")
    assert "openrouter" in available_providers(s)
    assert set(build_adapters(s)) == {"openai", "openrouter"}
