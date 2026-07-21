"""SOTIF-style adequacy & evidence report (design brief: Adequacy report —
PWCC score, uncovered mass, per-combination exposure table, stop/continue
verdict; Markdown/PDF evidence artifact for safety cases).

Inputs are the artifacts the campaign already produced — the adequacy JSON
from ``assess --json`` (verdicts + gaps), optionally the exposure ledger CSV
from ``assess --ledger`` and a physcheck SARIF from ``lint --format sarif``.
Every input is fingerprinted (SHA-256) so the artifact is traceable evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["build_report", "render_pdf"]


@dataclass
class _Inputs:
    adequacy: dict[str, Any]
    adequacy_path: Path
    ledger_path: Path | None = None
    sarif: dict[str, Any] | None = None
    sarif_path: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}f}"


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


# ── sections ────────────────────────────────────────────────────────────────


def _verdict_section(results: list[dict[str, Any]]) -> list[str]:
    rows = []
    for r in results:
        rows.append(
            [
                str(r["t"]),
                _fmt(r["alpha"], 3),
                _fmt(r["rho"], 5),
                _fmt(r["factor_F"], 2),
                _fmt(r["epsilon"], 4),
                str(r["n_combinations"]),
                str(r["n_sufficient"]),
                str(r["n_insufficient"]),
                _fmt(r["covered_mass"]),
                _fmt(r["uncovered_mass"]),
                f"**{r['verdict']}**",
            ]
        )
    lines = ["## Adequacy verdict", ""]
    lines += _md_table(
        ["t", "α", "ρ", "F", "ε", "combos", "sufficient", "insufficient",
         "PWCC (covered)", "uncovered", "verdict"],
        rows,
    )
    overall = all(r["is_adequate"] for r in results)
    lines += [
        "",
        (
            "**STOP — the campaign is adequate at every assessed t.**"
            if overall
            else "**CONTINUE — testing is not yet adequate; the gap list "
            "below is the next batch's target.**"
        ),
    ]
    return lines


def _argument_section(results: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## The adequacy argument (ISO 21448 / SOTIF framing)",
        "",
        "The operational model assigns every t-way combination of ODD "
        "feature values its expected share of real operation, P̃(c). A "
        "combination counts as *sufficiently tested* only when its "
        "accumulated exposure reaches E_min(c) = −ln(α)·P̃(c)/ρ — the "
        "exposure that bounds its residual event rate below the risk budget "
        "ρ (events/hour) with confidence 1−α. PWCC_t is the operational "
        "mass carried by sufficiently tested combinations; the suite is "
        "adequate when the *unassured* mass 1−PWCC_t stays below ε.",
        "",
    ]
    for r in results:
        lines.append(
            f"- **t={r['t']}**: the executed suite sufficiently exercises "
            f"combinations carrying **{_fmt(100 * r['covered_mass'], 2)} %** "
            f"of modelled operation; the residual unassured mass is "
            f"**{_fmt(r['uncovered_mass'])}** against ε = {r['epsilon']} — "
            f"{r['verdict']}."
        )
    lines += [
        "",
        "*Adequacy is a coverage claim, not a fault-absence claim: failures "
        "observed during execution are triaged separately and are not "
        "discharged by this report.*",
    ]
    return lines


def _lint_section(sarif: dict[str, Any], sarif_path: Path) -> list[str]:
    runs = sarif.get("runs", [])
    results = [res for run in runs for res in run.get("results", [])]
    tool = (runs[0].get("tool", {}).get("driver", {}) if runs else {})
    by_level: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    files = set()
    for res in results:
        by_level[res.get("level", "none")] = by_level.get(res.get("level", "none"), 0) + 1
        rule = res.get("ruleId", "?")
        by_rule[rule] = by_rule.get(rule, 0) + 1
        for loc in res.get("locations", []):
            uri = (
                loc.get("physicalLocation", {})
                .get("artifactLocation", {})
                .get("uri")
            )
            if uri:
                files.add(uri)
    lines = [
        "## Scenario validity (physcheck)",
        "",
        f"Lint evidence: `{sarif_path.name}` — "
        f"{tool.get('name', 'physcheck')} {tool.get('version', '')}, "
        f"{len(results)} finding(s) across {len(files)} file(s): "
        + ", ".join(f"{n} {lvl}" for lvl, n in sorted(by_level.items()))
        + ".",
    ]
    if by_rule:
        top = sorted(by_rule.items(), key=lambda kv: -kv[1])[:10]
        lines += ["", *_md_table(
            ["rule", "findings"], [[rid, str(n)] for rid, n in top]
        )]
    return lines


def _ledger_section(ledger_path: Path, top: int) -> list[str]:
    import pandas as pd

    df = pd.read_csv(ledger_path)
    lines = ["## Per-combination exposure ledger", ""]
    for t, group in df.groupby("t"):
        shown = group.sort_values("credited_mass", ascending=False).head(top)
        lines += [
            f"### t = {t} — top {len(shown)} of {len(group)} combinations "
            f"by operational mass (full table: `{ledger_path.name}`)",
            "",
        ]
        rows = [
            [
                str(r["combination"]),
                _fmt(float(r["credited_mass"]), 6),
                _fmt(float(r["actual_exposure_h"]), 3),
                _fmt(float(r["required_exposure_h"]), 3),
                "yes" if bool(r["sufficient"]) else "**no**",
            ]
            for _, r in shown.iterrows()
        ]
        lines += _md_table(
            ["combination", "P̃(c)", "E(c) [h]", "E_min(c) [h]", "sufficient"],
            rows,
        )
        lines.append("")
    return lines


def _gaps_section(results: list[dict[str, Any]], top: int) -> list[str]:
    lines = ["## Insufficient combinations (next batch targets)", ""]
    for r in results:
        gaps = r.get("gaps", [])
        if not gaps:
            lines.append(f"t={r['t']}: none — every combination is sufficient.")
            continue
        shown = gaps[:top]
        lines += [
            f"### t = {r['t']} — top {len(shown)} of {len(gaps)} by residual mass",
            "",
        ]
        rows = [
            [
                g["combination"],
                _fmt(float(g["residual_mass"]), 6),
                _fmt(float(g["actual_exposure_h"]), 3),
                _fmt(float(g["required_exposure_h"]), 3),
            ]
            for g in shown
        ]
        lines += _md_table(
            ["combination", "residual mass", "E(c) [h]", "E_min(c) [h]"], rows
        )
        lines.append("")
    return lines


def _provenance_section(inputs: _Inputs) -> list[str]:
    from oddpilot import __version__

    entries = [("adequacy JSON", inputs.adequacy_path)]
    if inputs.ledger_path is not None:
        entries.append(("exposure ledger", inputs.ledger_path))
    if inputs.sarif_path is not None:
        entries.append(("lint SARIF", inputs.sarif_path))
    rows = [
        [label, f"`{path}`", f"`{_sha256(path)}`"] for label, path in entries
    ]
    return [
        "## Provenance",
        "",
        f"Generated by odd-pilot {__version__} on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        f"Operational model: `{inputs.adequacy.get('model', '?')}`; "
        f"execution log: `{inputs.adequacy.get('log', '?')}`.",
        "",
        *_md_table(["input", "path", "sha256"], rows),
    ]


# ── entry points ────────────────────────────────────────────────────────────


def build_report(
    adequacy_path: Path,
    *,
    ledger_path: Path | None = None,
    sarif_path: Path | None = None,
    title: str = "Test-campaign adequacy evidence",
    top: int = 30,
) -> str:
    adequacy = json.loads(adequacy_path.read_text())
    results = adequacy.get("results", [])
    if not results:
        raise ValueError(f"no results in adequacy JSON {adequacy_path}")
    inputs = _Inputs(
        adequacy=adequacy,
        adequacy_path=adequacy_path,
        ledger_path=ledger_path,
        sarif=json.loads(sarif_path.read_text()) if sarif_path else None,
        sarif_path=sarif_path,
    )
    lines: list[str] = [f"# {title}", ""]
    lines += _verdict_section(results)
    lines.append("")
    lines += _argument_section(results)
    lines.append("")
    if inputs.sarif is not None and inputs.sarif_path is not None:
        lines += _lint_section(inputs.sarif, inputs.sarif_path)
        lines.append("")
    if ledger_path is not None:
        lines += _ledger_section(ledger_path, top)
    lines += _gaps_section(results, top)
    lines.append("")
    lines += _provenance_section(inputs)
    lines.append("")
    return "\n".join(lines)


def render_pdf(markdown_path: Path, pdf_path: Path) -> None:
    """Render the Markdown artifact to PDF via pandoc (the only renderer we
    can rely on being reproducible); a clear error when it is missing."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise RuntimeError(
            "--pdf needs pandoc on PATH; the Markdown artifact was still "
            f"written to {markdown_path}"
        )
    subprocess.run(
        [pandoc, str(markdown_path), "-o", str(pdf_path), "--standalone"],
        check=True,
    )
