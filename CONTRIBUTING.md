# Contributing to odd-pilot

Thanks for your interest! This monorepo hosts `physcheck` (implemented) and `odd-pilot`
(skeleton). Contributions to the **rule catalog** are especially welcome — it is designed
as a community-maintained registry of scenario-validity knowledge.

## Contributing a rule

Rules live in [`physcheck/catalog/*.yaml`](physcheck/catalog/). Every rule MUST carry:

- `id` — stable, unique, `<GROUP>-<NNN>` (e.g. `ATM-002`); never reuse a retired id.
- `layer` — `L0`…`L6` per the layer taxonomy in the top-level README.
- `severity` — `error` (physically impossible), `warning` (implausible / never observed),
  or `info`.
- `when` / `assert` — the machine-checkable predicate (see
  [`physcheck/README.md`](physcheck/README.md) for the expression grammar), with SI units.
- `citation` — a **full citation to a primary source** (authors, title, venue, year,
  DOI/URL). Rules without a citable basis are not accepted; add them to the rejected
  appendix of `docs/catalog_report.md` instead, with the reason.
- A **violating fixture**: `physcheck/tests/fixtures/violating/<ID>.xosc` that triggers the
  rule, and no false positive on the valid fixtures.

Validate your pack before opening a PR:

```bash
physcheck rules lint physcheck/catalog/your_pack.yaml
pytest physcheck/tests
```

## Code contributions

- Python ≥ 3.10, pure Python, **no simulator dependencies** in `physcheck`.
- `ruff check` and `mypy` must pass (`pip install -e "physcheck/[dev]"`).
- Tests: `pytest` (+ `hypothesis` property tests where meaningful). Every bug fix gets a
  regression test.
- Keep the Scenario IR engine-agnostic: parsers map *into* the IR; rules read only the IR
  attribute view, never raw XML.

## Workflow

1. Fork, branch from `main`.
2. `pip install -e "physcheck/[dev]"`.
3. Make your change + tests + (for rules) catalog entry with citation.
4. `ruff check physcheck && mypy physcheck/src && pytest physcheck/tests`.
5. Open a PR describing *why* (for rules: the physical argument and the source).

## Interpretation decisions

Non-obvious semantic choices (unit ambiguities in the OSC spec, tolerance values, …) are
recorded in [`docs/decisions.md`](docs/decisions.md). If your change embodies such a
decision, add an entry.

By contributing you agree that your contributions are licensed under Apache-2.0.
