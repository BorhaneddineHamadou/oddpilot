"""physcheck command-line interface.

Commands (design brief §7(b)):

    physcheck lint <paths...> [--map X.xodr] [--odd odd.yaml] [--rules PACK]
                   [--layers L0,L1] [--severity error|warning|info]
                   [--format table|json|sarif|html] [-o FILE]
                   [--fail-on error|warning|info|never] [--explain RULE-ID]
    physcheck rules list [--layer Lx]
    physcheck rules show <RULE-ID>
    physcheck rules lint <pack.yaml>

Exit codes: 0 success, 1 findings at/above --fail-on, 3 usage/config error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from physcheck import __version__
from physcheck.engine.catalog import RuleSpec, load_default_packs, load_pack
from physcheck.engine.engine import SEVERITY_ORDER, Finding, LintResult, lint_scenario
from physcheck.engine.plugins import PLUGIN_RULES
from physcheck.ir.model import Scenario
from physcheck.ir.osc_parser import parse_file
from physcheck.report.formats import render_report
from physcheck.xodr import XodrMap, load_map

__all__ = ["entrypoint", "main"]

_DEFAULT_LAYERS = "L0,L1"


class _Parser(argparse.ArgumentParser):
    """argparse that exits 3 (not 2) on usage errors, per the CLI contract."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(3)


def _build_parser() -> _Parser:
    parser = _Parser(prog="physcheck", description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", action="version", version=f"physcheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="lint OpenSCENARIO files or directories")
    lint.add_argument("paths", nargs="+", help=".xosc files or directories")
    lint.add_argument(
        "--map",
        dest="map_file",
        help="OpenDRIVE map for L2/L3 cross-checks (enables L2+L3; without --map, "
        "L2/L3 resolve each scenario's RoadNetwork/LogicFile)",
    )
    lint.add_argument("--odd", dest="odd_file",
                      help="ODD definition YAML for L5 conformance (enables L5)")
    lint.add_argument("--model", dest="model_file",
                      help="operational model (.bn, odd-pilot) for L6 statistical "
                           "plausibility (enables L6; needs odd-pilot installed)")
    lint.add_argument("--l6-quantile", type=float, default=0.01,
                      help="quantile floor for L6 never-observed warnings")
    lint.add_argument("--rules", action="append", default=[], help="additional rule pack YAML")
    lint.add_argument("--layers", default=_DEFAULT_LAYERS, help="comma list (default L0,L1)")
    lint.add_argument(
        "--severity",
        choices=["error", "warning", "info"],
        default="error",
        help="minimum severity to report (default: error)",
    )
    lint.add_argument("--format", choices=["table", "json", "sarif", "html"], default="table")
    lint.add_argument("-o", "--output", help="write report to file instead of stdout")
    lint.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "never"],
        default="error",
        help="exit 1 when findings at/above this severity exist (default: error)",
    )
    lint.add_argument("--explain", metavar="RULE-ID", help="explain findings of one rule")
    lint.add_argument("-v", "--verbose", action="count", default=0)

    rules = sub.add_parser("rules", help="inspect or validate rule packs")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_list = rules_sub.add_parser("list", help="enumerate the catalog")
    rules_list.add_argument("--layer", help="filter by layer, e.g. L1")
    rules_show = rules_sub.add_parser("show", help="show one rule in full")
    rules_show.add_argument("rule_id")
    rules_lint = rules_sub.add_parser("lint", help="validate a custom rule pack")
    rules_lint.add_argument("pack")
    return parser


def _load_rules(extra_packs: list[str]) -> tuple[list[RuleSpec], list[str]]:
    rules, errors = load_default_packs()
    for pack in extra_packs:
        extra, extra_errors = load_pack(pack)
        rules.extend(extra)
        errors.extend(extra_errors)
    return rules, errors


def _collect_files(paths: list[str]) -> list[Path] | None:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.xosc")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"physcheck: path not found: {p}", file=sys.stderr)
            return None
    return files


def _cmd_lint(args: argparse.Namespace) -> int:
    layers = {part.strip() for part in args.layers.split(",") if part.strip()}
    if args.map_file:
        layers.update(("L2", "L3"))
    odd_def = None
    if args.odd_file:
        if not Path(args.odd_file).is_file():
            print(f"physcheck: odd definition not found: {args.odd_file}", file=sys.stderr)
            return 3
        from physcheck.odd import load_odd

        odd_def = load_odd(args.odd_file)
        layers.add("L5")
    scorer = None
    if args.model_file:
        try:
            from oddpilot.statistical import (  # type: ignore[import-not-found]
                scorer_for,
            )
        except ImportError:
            print(
                "physcheck: --model (L6) needs the odd-pilot package installed",
                file=sys.stderr,
            )
            return 3
        try:
            scorer = scorer_for(args.model_file)
        except (OSError, ValueError) as exc:
            print(f"physcheck: cannot use model for L6: {exc}", file=sys.stderr)
            return 3
        layers.add("L6")
    unknown = layers - {f"L{i}" for i in range(7)}
    if unknown:
        print(f"physcheck: unknown layers: {sorted(unknown)}", file=sys.stderr)
        return 3
    not_shipped = layers - {"L0", "L1", "L2", "L3", "L4", "L5", "L6"}
    if not_shipped:
        print(
            f"physcheck: note: layers {sorted(not_shipped)} have no rules yet",
            file=sys.stderr,
        )
    if args.map_file and not Path(args.map_file).is_file():
        print(f"physcheck: map not found: {args.map_file}", file=sys.stderr)
        return 3

    rules, pack_errors = _load_rules(args.rules)
    if pack_errors:
        for err in pack_errors:
            print(f"physcheck: rule pack error: {err}", file=sys.stderr)
        return 3

    files = _collect_files(args.paths)
    if files is None:
        return 3
    if not files:
        print("physcheck: no .xosc files found", file=sys.stderr)
        return 3

    results: list[LintResult] = []
    map_cache: dict[str, XodrMap | None] = {}
    unmapped = 0
    for path in files:
        scenario = parse_file(path)
        xodr_map = None
        if "L2" in layers or "L3" in layers:
            xodr_map = _map_for(scenario, path, args.map_file, map_cache)
            if xodr_map is None:
                unmapped += 1
        results.append(
            lint_scenario(
                scenario, rules, layers, xodr_map=xodr_map, odd=odd_def,
                scorer=scorer, l6_quantile=args.l6_quantile,
            )
        )
    if unmapped:
        print(
            f"physcheck: note: map cross-checks skipped for {unmapped} file(s) with "
            "no resolvable OpenDRIVE map (pass --map or declare RoadNetwork/"
            "LogicFile); map-free L3 rules still ran",
            file=sys.stderr,
        )

    threshold = SEVERITY_ORDER[args.severity]
    all_findings = [f for r in results for f in r.findings]
    suppressed = sum(1 for f in all_findings if SEVERITY_ORDER[f.severity] < threshold)
    shown_results = [
        LintResult(
            file=r.file,
            findings=[f for f in r.findings if SEVERITY_ORDER[f.severity] >= threshold],
            document_kind=r.document_kind,
            rules_evaluated=r.rules_evaluated,
            rules_skipped=r.rules_skipped,
        )
        for r in results
    ]

    report = render_report(shown_results, args.format, rules)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"physcheck: report written to {args.output}", file=sys.stderr)
    else:
        print(report)
    if suppressed and args.format == "table" and not args.output:
        print(
            f"({suppressed} finding(s) below severity '{args.severity}' suppressed; "
            "use --severity warning|info to show them)",
        )

    if args.explain:
        _explain(args.explain, all_findings, rules)

    if args.fail_on != "never":
        fail_threshold = SEVERITY_ORDER[args.fail_on]
        if any(SEVERITY_ORDER[f.severity] >= fail_threshold for f in all_findings):
            return 1
    return 0


def _map_for(
    scenario: Scenario,
    scenario_path: Path,
    map_flag: str | None,
    cache: dict[str, XodrMap | None],
) -> XodrMap | None:
    """The OpenDRIVE map for one scenario: --map flag, else RoadNetwork/LogicFile."""
    if map_flag:
        candidate = Path(map_flag)
    elif scenario.road_network_logic_file:
        candidate = scenario_path.parent / scenario.road_network_logic_file
    else:
        return None
    key = str(candidate.resolve())
    if key not in cache:
        cache[key] = load_map(candidate) if candidate.is_file() else None
    return cache[key]


def _explain(rule_id: str, findings: list[Finding], rules: list[RuleSpec]) -> None:
    print(f"\n--- explain {rule_id} ---")
    spec = next((r for r in rules if r.id == rule_id), None)
    if spec is not None:
        print(f"{spec.id} [{spec.layer}/{spec.severity}] {spec.title}")
        if spec.when:
            print(f"  when:   {spec.when}")
        print(f"  assert: {spec.assert_expr}")
        if spec.quantitative_basis:
            print(f"  basis:  {spec.quantitative_basis}")
        print(f"  cite:   {spec.citation_str}")
    elif rule_id in PLUGIN_RULES:
        p_layer, severity, title, citation = PLUGIN_RULES[rule_id]
        print(f"{rule_id} [{p_layer}/{severity}] {title} (builtin plugin rule)")
        print(f"  cite:   {citation}")
    else:
        print(f"  unknown rule id {rule_id!r}")
        return
    matching = [f for f in findings if f.rule_id == rule_id]
    if not matching:
        print("  no findings of this rule in the linted files")
    for f in matching:
        print(f"  {f.file} [{f.context}]")
        for name, value in f.values.items():
            print(f"    {name} = {value}")


def _cmd_rules(args: argparse.Namespace) -> int:
    if args.rules_command == "lint":
        loaded, errors = load_pack(args.pack)
        if errors:
            for err in errors:
                print(f"physcheck: {err}", file=sys.stderr)
            return 1
        print(f"{args.pack}: OK ({len(loaded)} rule(s))")
        return 0

    rules, pack_errors = load_default_packs()
    if pack_errors:
        for err in pack_errors:
            print(f"physcheck: rule pack error: {err}", file=sys.stderr)
        return 3

    if args.rules_command == "list":
        specs = [r for r in rules if args.layer is None or r.layer == args.layer]
        plugin_rules = {
            rid: meta
            for rid, meta in PLUGIN_RULES.items()
            if args.layer is None or meta[0] == args.layer
        }
        print(f"{'ID':10s} {'LAYER':5s} {'SEVERITY':8s} {'PACK':14s} TITLE / SOURCE")
        for rule_id, (p_layer, severity, title, citation) in sorted(plugin_rules.items()):
            print(f"{rule_id:10s} {p_layer:5s} {severity:8s} {'builtin':14s} {title} — {citation}")
        for spec in sorted(specs, key=lambda r: r.id):
            source = str(spec.citation.get("source", ""))[:70]
            print(f"{spec.id:10s} {spec.layer:5s} {spec.severity:8s} {spec.pack:14s} "
                  f"{spec.title} — {source}")
        total = len(specs) + len(plugin_rules)
        print(f"\n{total} rule(s)")
        return 0

    if args.rules_command == "show":
        shown = next((r for r in rules if r.id == args.rule_id), None)
        if shown is None:
            if args.rule_id in PLUGIN_RULES:
                p_layer, severity, title, citation = PLUGIN_RULES[args.rule_id]
                print(f"{args.rule_id} [{p_layer}/{severity}] {title}")
                print("  builtin plugin rule (physcheck.engine.plugins)")
                print(f"  citation: {citation}")
                return 0
            print(f"physcheck: unknown rule id {args.rule_id!r}", file=sys.stderr)
            return 3
        print(f"{shown.id} [{shown.layer}/{shown.severity}] {shown.title}")
        print(f"  pack:    {shown.pack}")
        print(f"  scope:   {shown.scope}")
        if shown.when:
            print(f"  when:    {shown.when}")
        print(f"  assert:  {shown.assert_expr}")
        if shown.units:
            units = ", ".join(f"{k} [{v}]" for k, v in shown.units.items())
            print(f"  units:   {units}")
        print(f"  message: {shown.message}")
        if shown.quantitative_basis:
            print(f"  basis:   {shown.quantitative_basis}")
        print(f"  citation: {shown.citation_str}")
        return 0
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return code
    try:
        if args.command == "lint":
            return _cmd_lint(args)
        if args.command == "rules":
            return _cmd_rules(args)
    except OSError as exc:
        print(f"physcheck: {exc}", file=sys.stderr)
        return 3
    return 3


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
