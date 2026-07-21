# odd-pilot

Campaign copilot for scenario-based ADS testing. One campaign iteration:
**lint → execute (external) → assess → gaps → plan → lint → …**

Implemented (v0.5.0): `lint` (delegates to [`physcheck`](../physcheck/)),
`model` (learned operational distribution), `assess` (PWCC adequacy with a
risk-calibrated stopping rule), `gaps` (ranked coverage gaps), `plan`
(gap-targeted generation with the physcheck gate), `report` (SOTIF-style
evidence artifact), `loop` (executor-driven orchestration to adequacy), `conform`
(per-scenario ODD verdicts). Roadmap: `init`/`config` scaffolding.

```bash
pip install -e "odd-pilot/[dev]"

# 1. fit the operational model from a profiling table of real operation
#    (CSV/XLSX, one row per observed scenario, categorical feature_* columns)
odd-pilot model fit --data profiling.csv -o odd.bn --seed 7
odd-pilot model info odd.bn

# 2. assess how much expected real-world operation your executed tests
#    have adequately exercised (run log: feature_* + run_duration seconds)
odd-pilot assess --model odd.bn --log runs.csv --t 2 3 \
    --alpha 0.05 --rho 0.01 --epsilon 0.05 0.03
odd-pilot assess ... --fail-if-inadequate       # exit 2 unless adequate → CI gate
odd-pilot assess ... --sweep eps=0.01:0.10:0.01 # verdict sensitivity
odd-pilot assess ... --ledger ledger.csv --json summary.json

# 3. what to test next: insufficient combinations by residual operational mass
odd-pilot gaps --model odd.bn --log runs.csv --t 2 -n 20

# 4. generate the next batch, targeting the measured gaps
odd-pilot assess ... --json adequacy.json          # gaps travel in the JSON
odd-pilot plan --model odd.bn -a adequacy.json -k 20 \
    --template templates/junction.xosc -o batches/003/
odd-pilot plan ... --rarity                        # tail-focused (criticality mode)
odd-pilot plan ... --seed 42 --no-lint             # reproducible; skip the gate

# 5. the safety-case artifact: verdict, SOTIF argument, exposure ledger,
#    gap tables, lint summary, SHA-256 provenance of every input
odd-pilot assess ... --json adequacy.json --ledger ledger.csv
odd-pilot lint suite/ --format sarif -o lint.sarif
odd-pilot report -a adequacy.json --ledger ledger.csv --lint lint.sarif -o evidence.md
odd-pilot report ... --pdf                         # rendered PDF (needs pandoc)

# 6. or let odd-pilot drive the whole cycle through your simulator:
#    plan -> lint -> execute -> append runs.csv -> assess, until adequate
odd-pilot loop --model odd.bn --log runs.csv --template templates/junction.xosc \
    --exec "./run_carla.sh {scenario}" --until-adequate --max-iter 10
```

`loop` substitutes `{scenario}` per planned file and appends one run-log row
per successful execution (features + duration). Duration is the executor's
wall-clock time unless it prints `run_duration=<seconds>` on stdout — print
the *simulated* time there when the two diverge. Failed executions (non-zero
exit, `--timeout`) earn no exposure credit; an iteration whose executions all
fail aborts the loop. With `--until-adequate` the exit code is the campaign
gate: 0 adequate, 2 not.

## Gap-targeted generation (`plan`)

For each insufficient combination, highest residual mass first (budget `-k`
split proportionally to mass): condition the BN and draw a candidate pool
from P(X | c) — candidates satisfy the target condition while inheriting
naturalistic dependencies; select by max–min diversity in normalised
parameter space (`--rarity` inverts the pool ordering toward tail
conditions); instantiate each pick into the `--template`'s
`ParameterDeclarations` (feature `feature_x` fills the parameter named `x`);
and lint every instantiated scenario with physcheck L0–L3, discarding and
replacing violators — rarity-tail sampling stretches soft physical
dependencies, so linting inside generation is mandatory. Gaps whose whole
pool violates are reported as UNFILLABLE, never silently dropped. Output:
`plan.csv` (one row per scenario: target combination, residual mass, all
feature values, file) plus the instantiated `.xosc` files.

## The method (PWCC)

For every t-way combination c of ODD feature values:

- **P̃(c)** — credited operational mass, estimated by forward-sampling the
  Bayesian network (each sample credits its K = C(n,t) projections once, so
  Σ P̃(c) ≈ 1).
- **E(c)** — exposure: summed duration (hours) of executed runs consistent
  with c.
- **E_min(c) = −ln(α)·P̃(c)/ρ** — exposure needed to bound c's residual event
  rate below the risk budget ρ (events/h) with confidence 1−α.
- c is *sufficient* iff E(c) ≥ E_min(c); **PWCC_t = Σ_sufficient P̃(c)**;
  the suite is **adequate** when 1 − PWCC_t < ε — a bound on unassured
  operational mass usable directly in a SOTIF argument.

Adequacy is a coverage claim, not a fault-absence claim: observed failures
are triaged separately. Parameter guidance from the PWCC study: α and ρ only
enter through F = −ln(α)/ρ, and ε is the well-behaved knob — since mass
fragments as t grows, pass a *shrinking* per-t ε schedule
(`--epsilon 0.05 0.03 0.02` for `--t 2 3 4`).

The operational model is a discrete BN: structure by Hill-Climb Search
(BIC, random restarts), parameters by BDeu smoothing so every scenario keeps
non-zero probability (`model fit` refuses to save a model that fails
validation). `model` files from the original PWCC research repo load as-is.

## Provenance

Ported from the validated implementation of the PWCC research study
(training, assessment, and the vectorised credited-mass estimator), and
cross-validated against it on the study's deepscenario dataset: covered mass
agrees to < 0.15 % (Monte-Carlo tolerance), identical verdicts.
