"""load_configs parses the A-B YAML with sensible defaults."""

from pathlib import Path

import pytest

from eval.config import current_config, load_configs


def test_load_configs_parses_entries(tmp_path: Path) -> None:
    path = tmp_path / "configs.yaml"
    path.write_text(
        "- name: baseline\n"
        "  model: gpt-x\n"
        "- name: big\n"
        "  model: gpt-xl\n"
        "  fallback_model: gpt-x\n"
        "  prompt_version: sys-v2\n",
        encoding="utf-8",
    )
    configs = load_configs(path)
    assert [c.name for c in configs] == ["baseline", "big"]
    assert configs[0].fallback_model is None and configs[0].prompt_version == "sys-v1"
    assert configs[1].model == "gpt-xl" and configs[1].fallback_model == "gpt-x"
    assert configs[1].prompt_version == "sys-v2"


def test_load_configs_rejects_non_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("name: not-a-list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML list"):
        load_configs(path)


def test_current_config_from_settings() -> None:
    cfg = current_config()
    assert cfg.name == "current" and cfg.model and cfg.prompt_version
