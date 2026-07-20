"""Safe predicate expression language.

A restricted subset of Python expressions evaluated over a flat attribute
mapping with dotted names (``env.fog.visual_range_m``). Supported: literals,
arithmetic, comparisons (incl. chained), boolean operators, ``in``/``not in``
over list/tuple literals, and a whitelist of math functions plus
``exists('dotted.name')``.

Missing attributes raise :class:`MissingAttribute` during evaluation; the
engine maps this to "rule not applicable" (three-valued semantics, see
docs/decisions.md D7).
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["MissingAttribute", "Predicate", "PredicateError"]


class PredicateError(Exception):
    """The expression is not parseable / not in the allowed subset / mistyped."""


class MissingAttribute(Exception):
    """A referenced attribute is absent from the evaluation context."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan2": math.atan2,
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
    "radians": math.radians,
    "degrees": math.degrees,
}

_ALLOWED_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}

_ALLOWED_CMPOPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: bool(a == b),
    ast.NotEq: lambda a, b: bool(a != b),
    ast.Lt: lambda a, b: bool(a < b),
    ast.LtE: lambda a, b: bool(a <= b),
    ast.Gt: lambda a, b: bool(a > b),
    ast.GtE: lambda a, b: bool(a >= b),
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _dotted_name(node: ast.expr) -> str | None:
    """Return the dotted path for a Name/Attribute chain, else None."""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


class Predicate:
    """A compiled, validated predicate expression."""

    def __init__(self, source: str) -> None:
        self.source = source
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise PredicateError(f"syntax error in predicate {source!r}: {exc}") from exc
        self._root = tree.body
        self.names: set[str] = set()
        self._validate(self._root)

    def _validate(self, node: ast.expr) -> None:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str, bool)) and node.value is not None:
                raise PredicateError(f"literal {node.value!r} not allowed")
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in node.elts:
                self._validate(elt)
            return
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                self._validate(v)
            return
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
                raise PredicateError("unary operator not allowed")
            self._validate(node.operand)
            return
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BINOPS:
                raise PredicateError("binary operator not allowed")
            self._validate(node.left)
            self._validate(node.right)
            return
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _ALLOWED_CMPOPS:
                    raise PredicateError("comparison operator not allowed")
            self._validate(node.left)
            for comp in node.comparators:
                self._validate(comp)
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise PredicateError("only simple function calls are allowed")
            fname = node.func.id
            if fname != "exists" and fname not in _FUNCTIONS:
                raise PredicateError(f"function {fname!r} not allowed")
            if node.keywords:
                raise PredicateError("keyword arguments not allowed")
            if fname == "exists":
                if len(node.args) != 1 or not (
                    isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    raise PredicateError("exists() takes one string literal")
                return
            for arg in node.args:
                self._validate(arg)
            return
        dotted = _dotted_name(node)
        if dotted is not None:
            self.names.add(dotted)
            return
        raise PredicateError(
            f"expression element {ast.dump(node)} not allowed in predicate {self.source!r}"
        )

    def evaluate(self, attrs: Mapping[str, object]) -> object:
        """Evaluate against a flat attribute mapping.

        Raises MissingAttribute for absent names and PredicateError for type
        errors (e.g. comparing a string with a number).
        """
        try:
            return self._eval(self._root, attrs)
        except MissingAttribute:
            raise
        except PredicateError:
            raise
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise PredicateError(f"evaluation of {self.source!r} failed: {exc}") from exc

    def _eval(self, node: ast.expr, attrs: Mapping[str, object]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._eval(e, attrs) for e in node.elts]
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result: Any = True
                for v in node.values:
                    result = self._eval(v, attrs)
                    if not result:
                        return result
                return result
            for v in node.values:
                result = self._eval(v, attrs)
                if result:
                    return result
            return result
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, attrs)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.USub):
                return -operand
            return +operand
        if isinstance(node, ast.BinOp):
            return _ALLOWED_BINOPS[type(node.op)](
                self._eval(node.left, attrs), self._eval(node.right, attrs)
            )
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, attrs)
            for op, comp_node in zip(node.ops, node.comparators, strict=True):
                right = self._eval(comp_node, attrs)
                if not _ALLOWED_CMPOPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            if node.func.id == "exists":
                arg = node.args[0]
                assert isinstance(arg, ast.Constant)
                return str(arg.value) in attrs
            args = [self._eval(a, attrs) for a in node.args]
            return _FUNCTIONS[node.func.id](*args)
        dotted = _dotted_name(node)
        if dotted is not None:
            if dotted not in attrs:
                raise MissingAttribute(dotted)
            return attrs[dotted]
        raise PredicateError(f"unexpected node {ast.dump(node)}")
