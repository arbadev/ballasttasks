"""The production boundary precedes adapter construction, not just the first insert."""

import asyncio

import pytest

from app import seed_demo
from app.bootstrap import Container, Settings


def test_production_refuses_before_building_any_adapter(minimal_env: pytest.MonkeyPatch) -> None:
    minimal_env.setenv("APP__ENV", "production")
    built: list[Settings] = []

    def build(settings: Settings, **_: object) -> Container:
        built.append(settings)
        raise AssertionError("must not construct an adapter")

    minimal_env.setattr(seed_demo, "build_container", build)
    with pytest.raises(seed_demo.DemoSeedRefusedError, match="production"):
        asyncio.run(seed_demo.run())
    assert built == []


def test_entry_point_hides_configuration_values_on_failure(
    minimal_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    minimal_env.setenv("DATABASE__URL", "invalid://private-database-password")
    assert seed_demo.main() == 1
    output = capsys.readouterr()
    assert "Demo seed failed" in output.err
    assert "private-database-password" not in output.out + output.err
