#!/usr/bin/env python3
"""Lint every generated corpus with physcheck L0-L3 and tabulate physical
validity per generation strategy.

Usage:
    python3 analyze.py --map Town04.xodr [--corpora corpora] [--out results]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATEGIES = ["random", "pairwise", "search", "opmodel", "opmodel_gated"]


def lint(corpus: Path, map_path: Path, out_json: Path) -> dict:
    cmd = [
        sys.executable, "-m", "physcheck.cli", "lint", str(corpus),
        "--map", str(map_path), "--layers", "L0,L1,L2,L3",
        "--severity", "info", "--fail-on", "never",
        "--format", "json", "-o", str(out_json),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(out_json.read_text())


def summarise(report: dict) -> dict:
    files = report["files"]
    n = len(files)
    invalid = 0
    error_rules: Counter[str] = Counter()
    error_layers: Counter[str] = Counter()
    per_file_examples: list[str] = []
    for entry in files:
        errors = [f for f in entry.get("findings", []) if f["severity"] == "error"]
        if errors:
            invalid += 1
            if len(per_file_examples) < 3:
                worst = errors[0]
                per_file_examples.append(f"{worst['rule_id']}: {worst['message'][:110]}")
        layers_here = {f["layer"] for f in errors}
        for layer in layers_here:
            error_layers[layer] += 1
        for f in errors:
            error_rules[f["rule_id"]] += 1
    return {
        "n_files": n,
        "n_invalid": invalid,
        "pct_invalid": round(100 * invalid / n, 1) if n else 0.0,
        "error_files_by_layer": dict(sorted(error_layers.items())),
        "top_rules": error_rules.most_common(8),
        "examples": per_file_examples,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--corpora", type=Path, default=HERE / "corpora")
    ap.add_argument("--out", type=Path, default=HERE / "results")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict] = {}
    for strategy in STRATEGIES:
        corpus = args.corpora / strategy
        if not corpus.is_dir() or not list(corpus.glob("*.xosc")):
            print(f"[{strategy}] missing or empty — skipped")
            continue
        print(f"[{strategy}] linting ...")
        report = lint(corpus, args.map, args.out / f"raw_{strategy}.json")
        summaries[strategy] = summarise(report)

    lines = [
        "| Strategy | Scenarios | Physics-invalid | % invalid | Error files by layer | Top violated rules |",
        "|---|---|---|---|---|---|",
    ]
    for strategy, s in summaries.items():
        layers = ", ".join(f"{k}: {v}" for k, v in s["error_files_by_layer"].items()) or "—"
        rules = ", ".join(f"{r} ({n})" for r, n in s["top_rules"][:5]) or "—"
        lines.append(
            f"| {strategy} | {s['n_files']} | {s['n_invalid']} | "
            f"**{s['pct_invalid']}%** | {layers} | {rules} |"
        )
    table = "\n".join(lines)
    (args.out / "table.md").write_text(table + "\n")
    (args.out / "summary.json").write_text(json.dumps(summaries, indent=2))
    print()
    print(table)
    print(f"\nwrote {args.out}/table.md and summary.json")


if __name__ == "__main__":
    main()
