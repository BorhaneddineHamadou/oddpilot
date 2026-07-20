# physcheck

Standalone, layered physical-plausibility linter for ASAM OpenSCENARIO 1.x scenarios.
Pure Python ≥ 3.10; no simulator dependencies; the only runtime dependency is PyYAML.

```bash
pip install -e .
physcheck lint suite/ --format sarif -o lint.sarif --fail-on error
physcheck rules list --layer L1
physcheck rules show ATM-001
```

## Architecture

- **Scenario IR** (`physcheck.ir`): a typed, engine-agnostic intermediate representation.
  `physcheck.ir.osc_parser` maps OpenSCENARIO 1.0–1.3 XML into the IR (with
  ParameterDeclaration / `$param` / `${expr}` resolution). Rules never see raw XML — they
  read a flat, canonically named **attribute view** (`physcheck.ir.attributes`), documented
  in `../docs/attribute_space.md`.
- **Rule engine** (`physcheck.engine`): loads YAML rule packs (`catalog/*.yaml`) and Python
  plugin rules (`physcheck.engine.plugins`), evaluates predicates in a safe expression
  language, and emits findings.
- **Reports** (`physcheck.report`): `table` (terminal), `json`, `sarif` (2.1.0, GitHub code
  scanning ready), `html` (self-contained page).

## Rule YAML schema

```yaml
pack: atmosphere            # pack name
version: "0.1.0"
rules:
  - id: ATM-001             # stable unique id
    layer: L1               # L0..L6
    severity: error         # error | warning | info
    title: Dense fog implies short visual range
    scope: scenario         # scenario | entity | entity:pedestrian | entity:vehicle ...
    when: "env.fog.present"           # guard (optional): rule applies when true
    assert: "env.fog.visual_range_m < 2000"   # must hold, else finding
    message: "Fog is declared but visualRange={env.fog.visual_range_m} m ..."
    units: {env.fog.visual_range_m: m}
    citation:
      source: "..."
      authors: "..."
      year: 2024
      doi_or_url: "..."
    quantitative_basis: "..."
```

### Predicate expression language

A safe subset of Python expressions evaluated over the attribute view — names
(dotted attribute paths), numeric/string/bool literals, arithmetic (`+ - * / % **`),
comparisons (incl. chained), `and/or/not`, `in` over lists, function calls limited to
`abs, min, max, exists, sin, cos, tan, asin, acos, atan2, sqrt, log, exp, radians, degrees`.
Attributes that are absent make the enclosing `when` guard false (three-valued semantics)
unless tested with `exists(...)`; an `assert` that cannot be evaluated because of missing
attributes is skipped, never reported. See `../docs/decisions.md` (D7).

## Exit codes

`0` success (no findings at/above `--fail-on`), `1` findings at/above threshold,
`3` usage/config error.
