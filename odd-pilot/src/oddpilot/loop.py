"""Campaign orchestration (design brief §(g)): drive the full cycle
plan → lint → execute (external) → append run log → assess, through a
user-supplied executor command with ``{scenario}`` substituted per file.

The core never touches a simulator. Per executed scenario the run log gains
one row: the scenario's feature_* values plus its duration. The duration is
the executor's wall-clock time unless the executor prints an explicit
``run_duration=<seconds>`` line on stdout (simulated time and wall time
diverge on fast/slow hosts — printing it is the reliable way). Failed
executions (non-zero exit, timeout) earn no exposure credit and are
reported, not appended.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from oddpilot import plan as planner
from oddpilot.assess import AssessmentResult, assess
from oddpilot.opmodel import OperationalModel

__all__ = ["IterationOutcome", "LoopOutcome", "parse_duration", "run_loop"]

_DURATION_RE = re.compile(
    r"^\s*run_duration\s*[=:]?\s*([0-9]+(?:\.[0-9]*)?)\s*$", re.MULTILINE
)


def parse_duration(stdout: str) -> float | None:
    """Last ``run_duration=<seconds>`` line printed by the executor, if any."""
    matches = _DURATION_RE.findall(stdout)
    return float(matches[-1]) if matches else None


@dataclass
class IterationOutcome:
    index: int
    batch_dir: Path
    planned: int
    executed: int
    failed: int
    unfillable: int
    uncovered_mass: float
    adequate: bool


@dataclass
class LoopOutcome:
    iterations: list[IterationOutcome] = field(default_factory=list)
    adequate: bool = False
    stop_reason: str = ""


def _execute(
    cmd_template: str, scenario: Path, timeout: float | None
) -> tuple[bool, float, str]:
    """Run the executor for one scenario. Returns (ok, duration_s, detail)."""
    cmd = cmd_template.replace("{scenario}", str(scenario))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, 0.0, f"timeout after {timeout}s"
    wall = time.perf_counter() - t0
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, 0.0, f"exit {proc.returncode}" + (
            f": {tail[-1]}" if tail else ""
        )
    reported = parse_duration(proc.stdout or "")
    return True, reported if reported is not None else wall, ""


def _load_log(log_path: Path, feature_cols: list[str], duration_col: str) -> pd.DataFrame:
    if log_path.is_file():
        df = pd.read_csv(log_path)
        df.columns = df.columns.str.strip()
        return df
    return pd.DataFrame(columns=[*feature_cols, duration_col, "scenario_file"])


def run_loop(
    model: OperationalModel,
    log_path: Path,
    exec_cmd: str,
    template: Path,
    *,
    t: int = 2,
    alpha: float = 0.05,
    rho: float = 0.01,
    epsilon: float = 0.05,
    k: int = 10,
    max_iter: int = 10,
    batches_dir: Path = Path("batches"),
    pool_size: int = 100,
    seed: int | None = None,
    rarity: bool = False,
    lint: bool = True,
    duration_col: str = "run_duration",
    n_samples: int = 50_000,
    timeout: float | None = None,
    log_line: Any = print,
) -> LoopOutcome:
    """Iterate plan → execute → append → assess until adequate or max_iter."""
    outcome = LoopOutcome()
    runs = _load_log(log_path, model.feature_cols, duration_col)

    def _assess(frame: pd.DataFrame) -> AssessmentResult:
        return assess(
            model, frame, t=t, alpha=alpha, rho=rho, epsilon=epsilon,
            duration_col=duration_col, n_samples=n_samples, seed=seed,
        )

    result = _assess(runs)
    log_line(
        f"initial assessment: t={t} uncovered={result.uncovered_mass:.4f} "
        f"eps={epsilon} -> {'ADEQUATE' if result.is_adequate else 'INADEQUATE'}"
    )
    if result.is_adequate:
        outcome.adequate = True
        outcome.stop_reason = "already adequate before any iteration"
        return outcome

    for index in range(1, max_iter + 1):
        batch_dir = batches_dir / f"{index:03d}"
        iter_seed = None if seed is None else seed + index
        batch = planner.plan(
            model, result.gaps(), k,
            out_dir=batch_dir, template=template, lint=lint,
            rarity=rarity, pool_size=pool_size, seed=iter_seed,
        )
        if not batch.planned:
            outcome.stop_reason = (
                "planner produced no executable scenarios (all gaps "
                "unfillable) — no progress possible"
            )
            log_line(f"iteration {index}: {outcome.stop_reason}")
            break

        executed = failed = 0
        new_rows: list[dict[str, Any]] = []
        for planned in batch.planned:
            assert planned.file is not None  # template given -> file written
            ok, duration, detail = _execute(exec_cmd, planned.file, timeout)
            if not ok:
                failed += 1
                log_line(
                    f"iteration {index}: EXECUTION FAILED {planned.file.name} "
                    f"({detail}) — no exposure credited"
                )
                continue
            executed += 1
            new_rows.append(
                {
                    **planned.assignment,
                    duration_col: duration,
                    "scenario_file": str(planned.file),
                }
            )
        if new_rows:
            runs = pd.concat([runs, pd.DataFrame(new_rows)], ignore_index=True)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            runs.to_csv(log_path, index=False)

        result = _assess(runs)
        outcome.iterations.append(
            IterationOutcome(
                index=index,
                batch_dir=batch_dir,
                planned=len(batch.planned),
                executed=executed,
                failed=failed,
                unfillable=len(batch.unfillable),
                uncovered_mass=result.uncovered_mass,
                adequate=result.is_adequate,
            )
        )
        log_line(
            f"iteration {index}: planned={len(batch.planned)} "
            f"executed={executed} failed={failed} "
            f"uncovered={result.uncovered_mass:.4f} -> "
            f"{'ADEQUATE' if result.is_adequate else 'INADEQUATE'}"
        )
        if result.is_adequate:
            outcome.adequate = True
            outcome.stop_reason = f"adequate after iteration {index}"
            return outcome
        if executed == 0:
            outcome.stop_reason = (
                "every execution in the iteration failed — check the "
                "executor command"
            )
            log_line(f"iteration {index}: {outcome.stop_reason}")
            break
    else:
        outcome.stop_reason = f"max iterations ({max_iter}) reached"

    return outcome
