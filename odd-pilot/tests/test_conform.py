"""odd-pilot conform: L5 alone, per-scenario in/out/undeclared verdicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from oddpilot.cli import main

ODD = """
odd:
  name: mild-weather
  attributes:
    env.temperature_k:
      include: {min: 263, max: 313}
    env.road.wetness:
      exclude: [highFlooded]
"""


def _scenario(temp: float, wetness: str | None = "dry") -> str:
    road = f'<RoadCondition wetness="{wetness}"/>' if wetness else ""
    return f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader revMajor="1" revMinor="2" date="2026-07-21T12:00:00"
              description="conform test" author="odd-pilot"/>
  <Entities/>
  <Storyboard><Init><Actions>
    <GlobalAction><EnvironmentAction><Environment name="env">
      <Weather temperature="{temp}"/>
      {road}
    </Environment></EnvironmentAction></GlobalAction>
  </Actions></Init></Storyboard>
</OpenSCENARIO>"""


@pytest.fixture()
def suite(tmp_path: Path) -> tuple[Path, Path]:
    odd = tmp_path / "odd.yaml"
    odd.write_text(ODD)
    d = tmp_path / "suite"
    d.mkdir()
    (d / "in.xosc").write_text(_scenario(288))
    (d / "out.xosc").write_text(_scenario(250))
    (d / "undeclared.xosc").write_text(_scenario(288, wetness=None))
    return d, odd


def test_conform_verdicts_and_exit_code(
    suite: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    d, odd = suite
    code = main(["conform", str(d), "--odd", str(odd)])
    out = capsys.readouterr().out
    assert code == 1  # one scenario is OUT
    assert "in.xosc: IN" in out
    assert "out.xosc: OUT" in out
    assert "undeclared.xosc: UNDECLARED" in out
    assert "OUT         env.temperature_k = 250" in out


def test_conform_all_in_exits_zero(
    suite: tuple[Path, Path], tmp_path: Path
) -> None:
    _d, odd = suite
    only_in = tmp_path / "only_in"
    only_in.mkdir()
    (only_in / "a.xosc").write_text(_scenario(280))
    assert main(["conform", str(only_in), "--odd", str(odd)]) == 0
