"""odd-pilot CLI — campaign copilot for scenario-based ADS testing.

    odd-pilot lint <paths...>                     validate scenarios (physcheck)
    odd-pilot model fit --data profiling.csv -o odd.bn
    odd-pilot model info odd.bn
    odd-pilot assess --model odd.bn --log runs.csv --t 2 3 [--epsilon ...]
    odd-pilot gaps   --model odd.bn --log runs.csv --t 2 [-n 20]
    odd-pilot plan   --model odd.bn -a adequacy.json -k 20 --template t.xosc -o batch/
    odd-pilot report -a adequacy.json --lint lint.sarif -o evidence.md
    odd-pilot loop   --model odd.bn --log runs.csv --template t.xosc \\
                     --exec "./run_sim.sh {scenario}" --until-adequate --max-iter 10

Campaign loop: lint → execute (external) → assess → gaps → plan → lint → …
`conform` is a roadmap stub.

Exit codes: 0 success; 1 bad input; 2 assessment inadequate (with
--fail-if-inadequate); 3 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from oddpilot.assess import AssessmentResult

_STUBS = ("init", "config", "conform")


def _read_table(path: Path) -> pd.DataFrame:
    import pandas as pd

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    elif path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        raise ValueError(f"unsupported table format: {path.suffix}")
    df.columns = df.columns.str.strip()
    return df


# ── model ───────────────────────────────────────────────────────────────────


def _cmd_model(args: argparse.Namespace) -> int:
    from oddpilot import opmodel

    if args.model_command == "fit":
        df = _read_table(args.data)
        model = opmodel.fit(
            df,
            scoring=args.scoring,
            max_indegree=args.max_indegree,
            n_restarts=args.restarts,
            ess=args.ess,
            seed=args.seed,
        )
        model.save(args.output)
        meta = model.meta
        print(
            f"operational model fitted: {meta['n_nodes']} nodes, "
            f"{meta['n_edges']} edges from {meta['n_rows']} rows "
            f"(score {meta['fit_score']}, min CPT prob {meta['min_prob']})"
        )
        print(f"saved -> {args.output}")
        return 0
    if args.model_command == "info":
        model = opmodel.load(args.model_file)
        info = {"feature_cols": model.feature_cols, **model.meta}
        print(json.dumps(info, indent=2, default=str))
        return 0
    return 3


# ── assess / gaps ───────────────────────────────────────────────────────────


def _epsilons(t_values: list[int], epsilon: list[float]) -> dict[int, float]:
    """One ε for all t, or one ε per t (the study's t-adaptive schedule:
    mass fragments as t grows, so ε should shrink with t)."""
    if len(epsilon) == 1:
        return {t: epsilon[0] for t in t_values}
    if len(epsilon) == len(t_values):
        return dict(zip(t_values, epsilon, strict=True))
    raise ValueError(
        f"--epsilon takes 1 value or one per t ({len(t_values)} t values, "
        f"{len(epsilon)} epsilons given)"
    )


def _parse_sweep(spec: str) -> list[float]:
    """'eps=0.01:0.10:0.01' -> [0.01, 0.02, ..., 0.10]."""
    key, _, rng = spec.partition("=")
    if key.strip() not in ("eps", "epsilon") or not rng:
        raise ValueError(f"bad --sweep spec {spec!r}; expected eps=LO:HI:STEP")
    lo, hi, step = (float(x) for x in rng.split(":"))
    if step <= 0 or hi < lo:
        raise ValueError(f"bad --sweep range {rng!r}")
    out = []
    v = lo
    while v <= hi + 1e-12:
        out.append(round(v, 10))
        v += step
    return out


def _run_assessments(args: argparse.Namespace) -> list[AssessmentResult]:
    from oddpilot import assess as pwcc
    from oddpilot import opmodel

    model = opmodel.load(args.model)
    runs = _read_table(args.log)
    t_values = sorted(args.t)
    eps_by_t = _epsilons(t_values, args.epsilon)
    return [
        pwcc.assess(
            model,
            runs,
            t=t,
            alpha=args.alpha,
            rho=args.rho,
            epsilon=eps_by_t[t],
            duration_col=args.duration_col,
            n_samples=args.n_samples,
            seed=args.seed,
        )
        for t in t_values
    ]


def _cmd_assess(args: argparse.Namespace) -> int:
    results = _run_assessments(args)

    header = (
        f"{'t':>3} {'F':>9} {'eps':>7} {'combos':>8} {'insuff':>7} "
        f"{'covered':>9} {'uncovered':>10}  verdict"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        s = r.summary()
        print(
            f"{s['t']:>3} {s['factor_F']:>9.2f} {s['epsilon']:>7.4f} "
            f"{s['n_combinations']:>8} {s['n_insufficient']:>7} "
            f"{s['covered_mass']:>9.4f} {s['uncovered_mass']:>10.4f}  "
            f"{s['verdict']}"
        )

    if args.sweep:
        eps_grid = _parse_sweep(args.sweep)
        print(f"\nverdict sensitivity across epsilon ({args.sweep}):")
        for r in results:
            verdicts = ["A" if r.uncovered_mass < e else "-" for e in eps_grid]
            first = next((e for e in eps_grid if r.uncovered_mass < e), None)
            certifies = (
                f"certifies from eps >= {first}"
                if first is not None
                else "never certifies on this grid"
            )
            print(f"  t={r.t}: [{''.join(verdicts)}]  {certifies}")

    if args.json:
        payload = {
            "model": str(args.model),
            "log": str(args.log),
            "results": [
                {
                    **r.summary(),
                    "gaps": [
                        {
                            "combo": [list(pair) for pair in g["combo"]],
                            "combination": g["combination"],
                            "residual_mass": g["residual_mass"],
                            "actual_exposure_h": g["actual_exposure_h"],
                            "required_exposure_h": g["required_exposure_h"],
                        }
                        for g in r.gaps()
                    ],
                }
                for r in results
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"summary json -> {args.json}")
    if args.ledger:
        import pandas as pd

        pd.concat(
            [r.ledger().assign(t=r.t) for r in results], ignore_index=True
        ).to_csv(args.ledger, index=False)
        print(f"exposure ledger -> {args.ledger}")

    if args.fail_if_inadequate and not all(r.is_adequate for r in results):
        return 2
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    from oddpilot import opmodel
    from oddpilot import plan as planner

    model = opmodel.load(args.model)
    if args.adequacy is not None:
        payload = json.loads(Path(args.adequacy).read_text())
        gaps = planner.gaps_from_json(
            payload, t=args.t[0] if args.t is not None else None
        )
    else:
        if args.log is None:
            raise ValueError("plan needs either -a adequacy.json or --log runs.csv")
        if args.t is not None and len(args.t) > 1:
            raise ValueError("plan targets one t at a time")
        args.t = args.t or [2]
        results = _run_assessments(args)
        gaps = results[0].gaps()
    if not gaps:
        print("no gaps — the assessed suite is fully sufficient; nothing to plan")
        return 0
    if args.template is None and not args.no_lint:
        print(
            "odd-pilot plan: note: no --template given — emitting plan.csv only; "
            "the physcheck gate needs instantiated scenarios (--template)",
            file=sys.stderr,
        )
    result = planner.plan(
        model,
        gaps,
        args.batch,
        out_dir=args.out,
        template=args.template,
        lint=not args.no_lint,
        rarity=args.rarity,
        pool_size=args.pool,
        seed=args.seed,
    )
    print(
        f"planned {len(result.planned)} scenario(s) -> {args.out} "
        f"({result.n_discarded} candidate(s) discarded by the physcheck gate)"
    )
    for combo, mass, missing in result.unfillable:
        combo_str = " & ".join(f"{k}={v}" for k, v in combo)
        print(
            f"  UNFILLABLE: {combo_str} (residual {mass:.6f}) — {missing} "
            "scenario(s) short: every remaining candidate violates physics "
            "or the pool is exhausted",
            file=sys.stderr,
        )
    return 0


def _cmd_loop(args: argparse.Namespace) -> int:
    from oddpilot import opmodel
    from oddpilot.loop import run_loop

    if "{scenario}" not in args.exec_cmd:
        raise ValueError("--exec command must contain the {scenario} placeholder")
    model = opmodel.load(args.model)
    outcome = run_loop(
        model,
        args.log,
        args.exec_cmd,
        args.template,
        t=args.t[0] if args.t else 2,
        alpha=args.alpha,
        rho=args.rho,
        epsilon=args.epsilon[0],
        k=args.batch,
        max_iter=args.max_iter,
        batches_dir=args.batches_dir,
        pool_size=args.pool,
        seed=args.seed,
        rarity=args.rarity,
        lint=not args.no_lint,
        duration_col=args.duration_col,
        n_samples=args.n_samples,
        timeout=args.timeout,
    )
    print(f"loop finished: {outcome.stop_reason}")
    if args.until_adequate and not outcome.adequate:
        return 2
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from oddpilot import report as reporting

    markdown = reporting.build_report(
        args.adequacy,
        ledger_path=args.ledger,
        sarif_path=args.lint,
        title=args.title,
        top=args.top,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown)
    print(f"evidence artifact -> {args.output}")
    if args.pdf:
        pdf_path = args.output.with_suffix(".pdf")
        try:
            reporting.render_pdf(args.output, pdf_path)
        except RuntimeError as exc:
            print(f"odd-pilot report: {exc}", file=sys.stderr)
            return 1
        print(f"pdf -> {pdf_path}")
    return 0


def _cmd_gaps(args: argparse.Namespace) -> int:
    results = _run_assessments(args)
    for r in results:
        gaps = r.gaps(limit=args.top)
        print(
            f"t={r.t}: {r.summary()['n_insufficient']} insufficient "
            f"combinations, residual mass {r.uncovered_mass:.4f} "
            f"(showing top {len(gaps)})"
        )
        for g in gaps:
            print(
                f"  {g['residual_mass']:.6f}  {g['combination']}  "
                f"[{g['actual_exposure_h']:.3f}h / "
                f"{g['required_exposure_h']:.3f}h]"
            )
    if args.json:
        payload = {
            "results": [
                {
                    "t": r.t,
                    "gaps": [
                        {k: v for k, v in g.items() if k != "combo"}
                        for g in r.gaps(limit=args.top)
                    ],
                }
                for r in results
            ]
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"gaps json -> {args.json}")
    return 0


# ── parser ──────────────────────────────────────────────────────────────────


def _add_assess_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", type=Path, required=True, help="operational model (.bn)")
    p.add_argument("--log", type=Path, required=True, help="execution log CSV/XLSX")
    p.add_argument("--t", type=int, nargs="+", default=[2], metavar="T")
    p.add_argument("--alpha", type=float, default=0.05, help="miss probability")
    p.add_argument("--rho", type=float, default=0.01, help="risk budget, events/h")
    p.add_argument(
        "--epsilon", type=float, nargs="+", default=[0.05],
        help="adequacy bound(s): one value, or one per t (shrink with t)",
    )
    p.add_argument("--duration-col", default="run_duration",
                   help="run duration column, seconds")
    p.add_argument("--n-samples", type=int, default=50_000,
                   help="BN forward samples for the mass estimate")
    p.add_argument("--seed", type=int, default=None, help="sampling seed")
    p.add_argument("--json", type=Path, default=None, help="write JSON summary here")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odd-pilot", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    model = sub.add_parser("model", help="operational model (learned ODD distribution)")
    model_sub = model.add_subparsers(dest="model_command")
    fit = model_sub.add_parser("fit", help="fit a BN from a profiling table")
    fit.add_argument("--data", type=Path, required=True,
                     help="profiling CSV/XLSX with feature_* columns")
    fit.add_argument("-o", "--output", type=Path, required=True, help="output .bn")
    fit.add_argument("--scoring", choices=["bic", "k2"], default="bic")
    fit.add_argument("--max-indegree", type=int, default=4)
    fit.add_argument("--restarts", type=int, default=3)
    fit.add_argument("--ess", type=float, default=5.0,
                     help="BDeu equivalent sample size (smoothing)")
    fit.add_argument("--seed", type=int, default=None)
    info = model_sub.add_parser("info", help="show a saved model's metadata")
    info.add_argument("model_file", type=Path)

    assess_p = sub.add_parser("assess", help="PWCC adequacy of an execution log")
    _add_assess_args(assess_p)
    assess_p.add_argument("--ledger", type=Path, default=None,
                          help="write the per-combination exposure ledger CSV here")
    assess_p.add_argument("--sweep", default=None, metavar="eps=LO:HI:STEP",
                          help="verdict sensitivity across an epsilon grid")
    assess_p.add_argument("--fail-if-inadequate", action="store_true",
                          help="exit 2 unless every t is adequate")

    gaps_p = sub.add_parser("gaps", help="insufficient combinations by residual mass")
    _add_assess_args(gaps_p)
    gaps_p.add_argument("-n", "--top", type=int, default=20,
                        help="show the top N gaps")

    plan_p = sub.add_parser(
        "plan", help="generate the next batch targeting the measured gaps"
    )
    plan_p.add_argument("--model", type=Path, required=True,
                        help="operational model (.bn)")
    plan_p.add_argument("-a", "--adequacy", type=Path, default=None,
                        help="adequacy JSON from 'assess --json' (has the gaps)")
    plan_p.add_argument("--log", type=Path, default=None,
                        help="execution log — recompute gaps instead of -a")
    plan_p.add_argument("--t", type=int, nargs="+", default=None, metavar="T",
                        help="t to target (default: first inadequate in -a, else 2)")
    plan_p.add_argument("-k", "--batch", type=int, default=10,
                        help="number of scenarios to plan")
    plan_p.add_argument("-o", "--out", type=Path, default=Path("batch"),
                        help="output directory (plan.csv + scenarios)")
    plan_p.add_argument("--template", type=Path, default=None,
                        help="OpenSCENARIO template whose ParameterDeclarations "
                             "receive the feature values")
    plan_p.add_argument("--rarity", action="store_true",
                        help="prioritise tail conditions (criticality mode)")
    plan_p.add_argument("--no-lint", action="store_true",
                        help="skip the built-in physcheck gate")
    plan_p.add_argument("--pool", type=int, default=100,
                        help="conditional candidate pool size per gap")
    plan_p.add_argument("--seed", type=int, default=None)
    plan_p.add_argument("--alpha", type=float, default=0.05, help=argparse.SUPPRESS)
    plan_p.add_argument("--rho", type=float, default=0.01, help=argparse.SUPPRESS)
    plan_p.add_argument("--epsilon", type=float, nargs="+", default=[0.05],
                        help=argparse.SUPPRESS)
    plan_p.add_argument("--duration-col", default="run_duration",
                        help=argparse.SUPPRESS)
    plan_p.add_argument("--n-samples", type=int, default=50_000,
                        help=argparse.SUPPRESS)

    report_p = sub.add_parser(
        "report", help="SOTIF-style adequacy & evidence artifact (Markdown/PDF)"
    )
    report_p.add_argument("-a", "--adequacy", type=Path, required=True,
                          help="adequacy JSON from 'assess --json'")
    report_p.add_argument("--ledger", type=Path, default=None,
                          help="exposure ledger CSV from 'assess --ledger'")
    report_p.add_argument("--lint", type=Path, default=None,
                          help="physcheck SARIF from 'lint --format sarif'")
    report_p.add_argument("-o", "--output", type=Path, default=Path("evidence.md"))
    report_p.add_argument("--pdf", action="store_true",
                          help="also render a PDF (needs pandoc)")
    report_p.add_argument("--title", default="Test-campaign adequacy evidence")
    report_p.add_argument("--top", type=int, default=30,
                          help="rows per table in the artifact")

    loop_p = sub.add_parser(
        "loop", help="drive plan -> execute -> append -> assess to adequacy"
    )
    loop_p.add_argument("--model", type=Path, required=True,
                        help="operational model (.bn)")
    loop_p.add_argument("--log", type=Path, required=True,
                        help="run log CSV (created if missing; appended per run)")
    loop_p.add_argument("--exec", dest="exec_cmd", required=True,
                        metavar="CMD",
                        help="executor command; {scenario} is replaced per file")
    loop_p.add_argument("--template", type=Path, required=True,
                        help="OpenSCENARIO template for planned scenarios")
    loop_p.add_argument("--t", type=int, nargs="+", default=[2], metavar="T")
    loop_p.add_argument("--alpha", type=float, default=0.05)
    loop_p.add_argument("--rho", type=float, default=0.01)
    loop_p.add_argument("--epsilon", type=float, nargs="+", default=[0.05])
    loop_p.add_argument("-k", "--batch", type=int, default=10,
                        help="scenarios per iteration")
    loop_p.add_argument("--until-adequate", action="store_true",
                        help="exit 2 if the loop ends without adequacy")
    loop_p.add_argument("--max-iter", type=int, default=10)
    loop_p.add_argument("--batches-dir", type=Path, default=Path("batches"))
    loop_p.add_argument("--timeout", type=float, default=None,
                        help="seconds allowed per execution")
    loop_p.add_argument("--pool", type=int, default=100)
    loop_p.add_argument("--seed", type=int, default=None)
    loop_p.add_argument("--rarity", action="store_true")
    loop_p.add_argument("--no-lint", action="store_true")
    loop_p.add_argument("--duration-col", default="run_duration")
    loop_p.add_argument("--n-samples", type=int, default=50_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "lint":
        from physcheck.cli import main as physcheck_main

        return physcheck_main(args_list)
    if args_list and args_list[0] in _STUBS:
        print(
            f"odd-pilot {args_list[0]!r} is a roadmap stub — implemented so "
            "far: lint, model, assess, gaps.",
            file=sys.stderr,
        )
        return 3
    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "model":
            if args.model_command is None:
                print("odd-pilot model: choose 'fit' or 'info'", file=sys.stderr)
                return 3
            return _cmd_model(args)
        if args.command == "assess":
            return _cmd_assess(args)
        if args.command == "gaps":
            return _cmd_gaps(args)
        if args.command == "plan":
            return _cmd_plan(args)
        if args.command == "report":
            return _cmd_report(args)
        if args.command == "loop":
            return _cmd_loop(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"odd-pilot: {exc}", file=sys.stderr)
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
