from __future__ import annotations

from pathlib import Path

import pytest

from physcheck.engine.catalog import RuleSpec, load_default_packs

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def all_rules() -> list[RuleSpec]:
    rules, errors = load_default_packs()
    assert not errors, f"shipped packs must validate: {errors}"
    return rules
