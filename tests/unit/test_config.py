from pathlib import Path

import pytest
from pydantic import ValidationError

from popper.harness.config import load_config


def test_defaults_load() -> None:
    cfg = load_config(env={})
    assert cfg.search.num_drafts == 3
    assert cfg.execution.timeout_seconds == 300


def test_user_file_overrides_one_key(tmp_path: Path) -> None:
    user = tmp_path / "c.yaml"
    user.write_text("search: {num_drafts: 1}\n", encoding="utf-8")
    cfg = load_config(user, env={})
    assert cfg.search.num_drafts == 1
    assert cfg.search.debug_prob == 0.5


def test_popper_model_env_sets_every_role() -> None:
    cfg = load_config(env={"POPPER_MODEL": "m-sonnet"})
    assert {cfg.models.analyst, cfg.models.writer, cfg.models.theorist} == {"m-sonnet"}


def test_unknown_key_rejected(tmp_path: Path) -> None:
    user = tmp_path / "c.yaml"
    user.write_text("search: {nope: 1}\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(user, env={})


def test_default_models_are_named_by_function(tmp_path: Path) -> None:
    assert set(load_config(env={}).models.model_dump()) == {
        "theorist",
        "analyst",
        "judge",
        "writer",
    }
    user = tmp_path / "c.yaml"
    user.write_text("models: {code: x}\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(user, env={})


def test_route_must_match_exactly_one_price(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="route theorist"):
        load_config(env={"POPPER_MODEL": "some-other-model"})
    user = tmp_path / "c.yaml"
    user.write_text("budget: {prices: {claude: {input: 1, output: 1}}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected exactly one"):
        load_config(user, env={})


def test_haiku_model_selects_haiku_price() -> None:
    cfg = load_config(env={"POPPER_MODEL": "global.anthropic.claude-haiku-4-5"})
    assert cfg.budget.price(cfg.models.analyst).input == 1.0
