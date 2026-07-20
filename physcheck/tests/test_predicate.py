from __future__ import annotations

import pytest

from physcheck.engine.predicate import MissingAttribute, Predicate, PredicateError


def test_basic_comparison() -> None:
    assert Predicate("env.x < 10").evaluate({"env.x": 5}) is True
    assert Predicate("env.x < 10").evaluate({"env.x": 15}) is False


def test_chained_comparison() -> None:
    p = Predicate("0.8 <= env.f <= 1.2")
    assert p.evaluate({"env.f": 1.0}) is True
    assert p.evaluate({"env.f": 1.3}) is False
    assert p.evaluate({"env.f": 0.5}) is False


def test_membership_and_strings() -> None:
    p = Predicate("env.w in ['dry', 'moist']")
    assert p.evaluate({"env.w": "dry"})
    assert not p.evaluate({"env.w": "highFlooded"})


def test_boolean_logic_and_not() -> None:
    p = Predicate("not (env.a > 0 or env.b > 0)")
    assert p.evaluate({"env.a": -1, "env.b": -1})
    assert not p.evaluate({"env.a": 1, "env.b": -1})


def test_missing_attribute_raises() -> None:
    with pytest.raises(MissingAttribute):
        Predicate("env.absent > 1").evaluate({})


def test_exists() -> None:
    p = Predicate("exists('env.x') and env.x > 1")
    assert p.evaluate({"env.x": 2})
    assert not p.evaluate({})  # short-circuits, no MissingAttribute


def test_arithmetic_and_functions() -> None:
    p = Predicate("env.v <= 40000 * env.r ** -0.55")
    assert p.evaluate({"env.v": 100, "env.r": 50.0})
    assert not p.evaluate({"env.v": 100000, "env.r": 50.0})
    q = Predicate("env.l <= 1.15 * (127500 * exp(-0.21 / sin(env.h)) + 800)")
    assert q.evaluate({"env.h": 1.0, "env.l": 50000})


def test_type_error_is_predicate_error() -> None:
    with pytest.raises(PredicateError):
        Predicate("env.x > 1").evaluate({"env.x": "a-string"})


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os')",
        "().__class__",
        "open('/etc/passwd')",
        "lambda: 1",
        "[x for x in range(3)]",
        "env.x if True else 1",
        "f'{1}'",
        "x := 3",
        "env.x @ env.y",
    ],
)
def test_rejects_unsafe_constructs(bad: str) -> None:
    with pytest.raises(PredicateError):
        Predicate(bad)


def test_names_collected() -> None:
    p = Predicate("env.a > 1 and entity.b.c < 2")
    assert p.names == {"env.a", "entity.b.c"}
