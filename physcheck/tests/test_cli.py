from __future__ import annotations

import json
from pathlib import Path

import pytest

from physcheck.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VALID = str(FIXTURES / "valid")
VIOLATING_FILE = str(FIXTURES / "violating" / "KIN-001.xosc")


def test_lint_valid_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", VALID]) == 0


def test_lint_violation_exit_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", VIOLATING_FILE]) == 1
    out = capsys.readouterr().out
    assert "KIN-001" in out


def test_fail_on_never(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", VIOLATING_FILE, "--fail-on", "never"]) == 0


def test_fail_on_warning_catches_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    warning_file = str(FIXTURES / "violating" / "ATM-001.xosc")
    assert main(["lint", warning_file]) == 0  # only a warning; default fail-on error
    assert main(["lint", warning_file, "--fail-on", "warning"]) == 1


def test_severity_filter_hides_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    warning_file = str(FIXTURES / "violating" / "ATM-001.xosc")
    main(["lint", warning_file, "--fail-on", "never"])
    out = capsys.readouterr().out
    assert "ATM-001" not in out  # default --severity error hides it
    main(["lint", warning_file, "--fail-on", "never", "--severity", "warning"])
    out = capsys.readouterr().out
    assert "ATM-001" in out


def test_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    main(["lint", VIOLATING_FILE, "--format", "json", "--fail-on", "never",
          "--severity", "info"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["tool"]["name"] == "physcheck"
    ids = {f["rule_id"] for file in doc["files"] for f in file["findings"]}
    assert "KIN-001" in ids


def test_sarif_format(capsys: pytest.CaptureFixture[str]) -> None:
    main(["lint", VIOLATING_FILE, "--format", "sarif", "--fail-on", "never"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert "KIN-001" in rule_ids
    assert any(res["ruleId"] == "KIN-001" for res in run["results"])


def test_html_format_output_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_file = tmp_path / "report.html"
    main(["lint", VIOLATING_FILE, "--format", "html", "-o", str(out_file),
          "--fail-on", "never"])
    text = out_file.read_text()
    assert text.startswith("<!DOCTYPE html>")
    assert "KIN-001" in text


def test_explain(capsys: pytest.CaptureFixture[str]) -> None:
    main(["lint", VIOLATING_FILE, "--fail-on", "never", "--explain", "KIN-001"])
    out = capsys.readouterr().out
    assert "explain KIN-001" in out
    assert "hukin" in out  # citation DOI visible
    assert "entity.max_target_speed_mps" in out  # offending values


def test_usage_error_exit_three(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint"]) == 3
    assert main(["frobnicate"]) == 3
    assert main(["lint", "/nonexistent/path.xosc"]) == 3


def test_rules_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules", "list"]) == 0
    out = capsys.readouterr().out
    assert "ATM-001" in out and "SCH-001" in out
    assert main(["rules", "list", "--layer", "L1"]) == 0
    out = capsys.readouterr().out
    assert "ATM-001" in out and "SCH-101" not in out


def test_rules_show(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules", "show", "FRI-013"]) == 0
    out = capsys.readouterr().out
    assert "Gillespie" in out and "assert" in out
    assert main(["rules", "show", "NOPE-999"]) == 3


def test_rules_lint_valid_and_invalid(tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(
        """
pack: custom
version: "0.0.1"
rules:
  - id: CUST-001
    layer: L1
    severity: warning
    scope: scenario
    title: t
    assert: "1 < 2"
    message: m
    citation: {source: s, year: 2020, doi_or_url: u}
"""
    )
    assert main(["rules", "lint", str(good)]) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("pack: broken\nversion: '1'\nrules:\n  - id: X\n    layer: L9\n")
    assert main(["rules", "lint", str(bad)]) == 1


def test_lint_with_custom_pack(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pack = tmp_path / "custom.yaml"
    pack.write_text(
        """
pack: custom
version: "0.0.1"
rules:
  - id: CUST-100
    layer: L1
    severity: error
    scope: entity
    title: no pedestrians at all
    when: "entity.category == 'pedestrian'"
    assert: "1 < 0"
    message: pedestrians banned in this suite
    citation: {source: s, year: 2020, doi_or_url: u}
"""
    )
    assert main(["lint", VIOLATING_FILE, "--rules", str(pack), "--fail-on", "never",
                 "--severity", "info"]) == 0
    out = capsys.readouterr().out
    assert "CUST-100" in out


def test_lint_l2_with_map_flag(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = str(FIXTURES / "l2" / "MAP-004.xosc")
    tiny = str(FIXTURES / "maps" / "tiny.xodr")
    assert main(["lint", scenario, "--map", tiny]) == 1  # --map implies L2
    assert "MAP-004" in capsys.readouterr().out


def test_lint_l2_map_from_logic_file(capsys: pytest.CaptureFixture[str]) -> None:
    # No --map: L2 resolves RoadNetwork/LogicFile relative to the scenario.
    scenario = str(FIXTURES / "l2" / "MAP-001.xosc")
    assert main(["lint", scenario, "--layers", "L0,L1,L2"]) == 1
    assert "MAP-001" in capsys.readouterr().out


def test_lint_l2_clean_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    scenario = str(FIXTURES / "l2" / "valid_l2_clean.xosc")
    assert main(["lint", scenario, "--layers", "L0,L1,L2", "--fail-on", "warning"]) == 0


def test_lint_l2_without_map_notes_skip(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", VIOLATING_FILE, "--layers", "L0,L1,L2"]) == 1  # KIN-001 still fires
    assert "L2 skipped" in capsys.readouterr().err


def test_lint_missing_map_exit_three(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lint", VIOLATING_FILE, "--map", "/nonexistent/map.xodr"]) == 3
