"""Both refusals precede adapter construction, not just the first insert."""

import asyncio

import pytest

from app import seed_demo
from app.bootstrap import Container, Settings


def _refuse_construction(monkeypatch: pytest.MonkeyPatch) -> list[Settings]:
    built: list[Settings] = []

    def build(settings: Settings, **_: object) -> Container:
        built.append(settings)
        raise AssertionError("must not construct an adapter")

    monkeypatch.setattr(seed_demo, "build_container", build)
    return built


def test_production_refuses_before_building_any_adapter(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("APP__ENV", "production")
    built = _refuse_construction(minimal_env)
    with pytest.raises(seed_demo.DemoSeedRefusedError, match="production"):
        asyncio.run(seed_demo.run(confirmed=True))
    assert built == []


def test_missing_confirmation_refuses_before_building_any_adapter(
    minimal_env: pytest.MonkeyPatch,
) -> None:
    built = _refuse_construction(minimal_env)
    with pytest.raises(seed_demo.DemoSeedRefusedError, match=seed_demo.CONFIRM_FLAG):
        asyncio.run(seed_demo.run(confirmed=False))
    assert built == []


def test_unknown_arguments_refuse_before_building_any_adapter(
    minimal_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built = _refuse_construction(minimal_env)
    assert seed_demo.main([seed_demo.CONFIRM_FLAG, "--force"]) == 1
    assert seed_demo.CONFIRM_FLAG in capsys.readouterr().err
    assert built == []


def test_entry_point_hides_configuration_values_on_failure(
    minimal_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    minimal_env.setenv("DATABASE__URL", "invalid://private-database-password")
    assert seed_demo.main([seed_demo.CONFIRM_FLAG]) == 1
    output = capsys.readouterr()
    assert "Demo seed failed" in output.err
    assert "private-database-password" not in output.out + output.err
