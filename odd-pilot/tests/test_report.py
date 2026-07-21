"""odd-pilot report: the SOTIF-style evidence artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oddpilot import report as reporting
from oddpilot.cli import main


@pytest.fixture()
def adequacy(tmp_path: Path) -> Path:
    payload = {
        "model": "odd.bn",
        "log": "runs.csv",
        "results": [
            {
                "t": 2, "alpha": 0.05, "rho": 0.01, "factor_F": 299.57,
                "epsilon": 0.05, "n_bn_samples": 4000, "n_combinations": 10,
                "n_sufficient": 8, "n_insufficient": 2,
                "covered_mass": 0.96, "uncovered_mass": 0.04,
                "is_adequate": True, "verdict": "ADEQUATE",
                "gaps": [
                    {
                        "combo": [["feature_weather", "rain"],
                                  ["feature_road", "wetWithPuddles"]],
                        "combination": "feature_weather=rain & "
                                       "feature_road=wetWithPuddles",
                        "residual_mass": 0.03,
                        "actual_exposure_h": 0.5,
                        "required_exposure_h": 8.99,
                    },
                    {
                        "combo": [["feature_time", "night"]],
                        "combination": "feature_time=night",
                        "residual_mass": 0.01,
                        "actual_exposure_h": 0.0,
                        "required_exposure_h": 3.0,
                    },
                ],
            }
        ],
    }
    path = tmp_path / "adequacy.json"
    path.write_text(json.dumps(payload))
    return path


@pytest.fixture()
def sarif(tmp_path: Path) -> Path:
    payload = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "physcheck", "version": "0.3.0"}},
                "results": [
                    {
                        "ruleId": "FRI-001", "level": "error",
                        "locations": [{"physicalLocation": {
                            "artifactLocation": {"uri": "a.xosc"}}}],
                    },
                    {
                        "ruleId": "FRI-002", "level": "warning",
                        "locations": [{"physicalLocation": {
                            "artifactLocation": {"uri": "b.xosc"}}}],
                    },
                ],
            }
        ],
    }
    path = tmp_path / "lint.sarif"
    path.write_text(json.dumps(payload))
    return path


def test_report_contains_the_evidence(adequacy: Path, sarif: Path) -> None:
    md = reporting.build_report(adequacy, sarif_path=sarif)
    assert "# Test-campaign adequacy evidence" in md
    assert "**ADEQUATE**" in md
    assert "STOP — the campaign is adequate" in md
    assert "96.00 %" in md  # covered mass in the SOTIF argument
    assert "coverage claim, not a fault-absence claim" in md
    assert "physcheck 0.3.0" in md and "1 error" in md and "1 warning" in md
    assert "feature_weather=rain & feature_road=wetWithPuddles" in md
    assert "sha256" in md and adequacy.name in md


def test_report_continue_verdict(adequacy: Path, tmp_path: Path) -> None:
    payload = json.loads(adequacy.read_text())
    payload["results"][0].update(
        {"is_adequate": False, "verdict": "INADEQUATE", "uncovered_mass": 0.2}
    )
    path = tmp_path / "inadequate.json"
    path.write_text(json.dumps(payload))
    md = reporting.build_report(path)
    assert "CONTINUE — testing is not yet adequate" in md


def test_report_with_ledger(adequacy: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "combination,credited_mass,actual_exposure_h,required_exposure_h,"
        "sufficient,t\n"
        "feature_weather=rain,0.3,10.0,89.87,False,2\n"
        "feature_weather=dry,0.7,300.0,209.7,True,2\n"
    )
    md = reporting.build_report(adequacy, ledger_path=ledger)
    assert "Per-combination exposure ledger" in md
    assert "feature_weather=dry" in md


def test_cli_report_and_missing_pandoc(
    adequacy: Path, sarif: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "evidence.md"
    assert main(
        ["report", "-a", str(adequacy), "--lint", str(sarif), "-o", str(out)]
    ) == 0
    assert out.exists() and "Adequacy verdict" in out.read_text()

    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    code = main(["report", "-a", str(adequacy), "-o", str(out), "--pdf"])
    assert code == 1  # graceful: markdown written, pandoc absence reported
    assert "pandoc" in capsys.readouterr().err
    assert out.exists()
