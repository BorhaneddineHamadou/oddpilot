"""L4 storyboard logic: static analysis of the scenario's control structure.

Design brief §4 L4: dead triggers (conditions that can never fire),
conflicting simultaneous actions on one actor, unreachable acts/events,
unit-incompatible comparisons — a conservative subset shipped first: every
rule here fires only on statically certain defects. Interpretation decision
D35 in docs/decisions.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physcheck.ir.model import Scenario, TriggerIR

if TYPE_CHECKING:  # imported late at runtime to avoid a cycle with engine.py
    from physcheck.engine.engine import Finding

__all__ = ["PLUGIN_RULES", "storyboard_findings"]

#: id -> (layer, severity, title, citation)
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    "STB-001": (
        "L4", "error",
        "Act stops at or before it starts",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Act (StartTrigger/"
        "StopTrigger define the act's activity interval)",
    ),
    "STB-002": (
        "L4", "error",
        "Trigger can never fire before the scenario ends",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Storyboard "
        "(StopTrigger ends the simulation; a start time at or beyond it is "
        "dead code)",
    ),
    "STB-003": (
        "L4", "error",
        "Conflicting simultaneous actions on one control channel",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Event (actions of "
        "one event start together; two motion controllers on the same "
        "longitudinal/lateral channel contend for the same degree of freedom)",
    ),
    "STB-004": (
        "L4", "error",
        "maximumExecutionCount of zero: never executes",
        "ASAM OpenSCENARIO 1.x Model Documentation, attribute "
        "maximumExecutionCount (number of allowed executions)",
    ),
    "STB-005": (
        "L4", "error",
        "ManeuverGroup with events but no actors",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Actors (private "
        "actions require an actor to apply to)",
    ),
    "STB-006": (
        "L4", "warning",
        "Storyboard declares no stop trigger",
        "ASAM OpenSCENARIO 1.x Model Documentation, class Storyboard "
        "(without a StopTrigger the scenario has no declared termination)",
    ),
    "STB-007": (
        "L4", "error",
        "Parameter compared numerically to a non-numeric value",
        "ASAM OpenSCENARIO 1.x Model Documentation, class ParameterCondition "
        "(relational rules require comparable operand types)",
    ),
}

_NUMERIC_RULES = {"greaterThan", "lessThan", "greaterOrEqual", "lessOrEqual"}
_MOTION_CHANNELS = ("longitudinal", "lateral")


def _mk(rule_id: str, message: str, scenario: Scenario, context: str,
        values: dict[str, object]) -> Finding:
    from physcheck.engine.engine import Finding

    layer, severity, title, citation = PLUGIN_RULES[rule_id]
    return Finding(
        rule_id=rule_id, severity=severity, layer=layer, title=title,
        message=message, file=scenario.source_path, context=context,
        values=values, citation=citation,
    )


def _sim_start_bound(trigger: TriggerIR | None) -> float | None:
    """Earliest simulation time at which the trigger CAN fire, when that is
    statically certain: every condition group needs a greaterThan-style
    simulation-time condition, and the trigger fires no earlier than the
    smallest such bound across groups (OR semantics)."""
    if trigger is None or not trigger.groups:
        return None
    bounds: list[float] = []
    for group in trigger.groups:
        times = [
            c.time_s + c.delay_s for c in group
            if c.kind == "simulation_time" and c.time_s is not None
            and c.rule in ("greaterThan", "greaterOrEqual")
        ]
        if not times:
            return None  # this group could fire earlier via other conditions
        bounds.append(max(times))  # AND within the group
    return min(bounds)  # OR across groups


def _sim_stop_bound(trigger: TriggerIR | None) -> float | None:
    """Latest simulation time by which the trigger HAS fired, when certain:
    some condition group consists solely of greaterThan-style simulation-time
    conditions — that group fires at its bound regardless of anything else."""
    if trigger is None:
        return None
    bounds = []
    for group in trigger.groups:
        if group and all(
            c.kind == "simulation_time" and c.time_s is not None
            and c.rule in ("greaterThan", "greaterOrEqual")
            for c in group
        ):
            bounds.append(
                max(c.time_s + c.delay_s for c in group if c.time_s is not None)
            )
    return min(bounds) if bounds else None


def storyboard_findings(scenario: Scenario) -> list[Finding]:
    sb = scenario.storyboard
    if sb is None:
        return []
    findings: list[Finding] = []

    scenario_end = _sim_stop_bound(sb.stop_trigger)
    if sb.stop_trigger is None or not sb.stop_trigger.groups:
        findings.append(
            _mk(
                "STB-006",
                "The storyboard has no StopTrigger condition: the scenario "
                "declares no termination and runs until the engine gives up.",
                scenario, "Storyboard", {},
            )
        )

    for act in sb.acts:
        start = _sim_start_bound(act.start_trigger)
        stop = _sim_stop_bound(act.stop_trigger)
        if start is not None and stop is not None and stop <= start:
            findings.append(
                _mk(
                    "STB-001",
                    f"Act '{act.name}' stops at t={stop} s but cannot start "
                    f"before t={start} s: its activity interval is empty — "
                    "the act never runs.",
                    scenario, act.label,
                    {"act.start_s": start, "act.stop_s": stop},
                )
            )
        for trigger, label, what in (
            (act.start_trigger, act.label, f"act '{act.name}'"),
        ):
            bound = _sim_start_bound(trigger)
            if bound is not None and scenario_end is not None and bound >= scenario_end:
                findings.append(
                    _mk(
                        "STB-002",
                        f"Start trigger of {what} cannot fire before "
                        f"t={bound} s, but the storyboard stops at "
                        f"t={scenario_end} s — dead trigger.",
                        scenario, label,
                        {"trigger.earliest_s": bound, "storyboard.stop_s": scenario_end},
                    )
                )
        for group in act.groups:
            if group.maximum_execution_count == 0:
                findings.append(
                    _mk(
                        "STB-004",
                        f"ManeuverGroup '{group.name}' declares "
                        "maximumExecutionCount=0: it can never execute.",
                        scenario, group.label, {},
                    )
                )
            private_events = [
                e for e in group.events
                if any(c != "global" for _n, c in e.actions)
            ]
            if (
                private_events
                and not [a for a in group.actors if a]
                and not group.select_triggering_entities
            ):
                findings.append(
                    _mk(
                        "STB-005",
                        f"ManeuverGroup '{group.name}' contains "
                        f"{len(private_events)} event(s) with private "
                        "actions but declares no actors: those actions "
                        "apply to nobody. (Groups holding only global "
                        "actions legitimately need no actors.)",
                        scenario, group.label,
                        {"group.private_events": len(private_events)},
                    )
                )
            for event in group.events:
                if event.maximum_execution_count == 0:
                    findings.append(
                        _mk(
                            "STB-004",
                            f"Event '{event.name}' declares "
                            "maximumExecutionCount=0: it can never execute.",
                            scenario, event.label, {},
                        )
                    )
                bound = _sim_start_bound(event.start_trigger)
                if (
                    bound is not None and scenario_end is not None
                    and bound >= scenario_end
                ):
                    findings.append(
                        _mk(
                            "STB-002",
                            f"Start trigger of event '{event.name}' cannot "
                            f"fire before t={bound} s, but the storyboard "
                            f"stops at t={scenario_end} s — dead trigger.",
                            scenario, event.label,
                            {"trigger.earliest_s": bound,
                             "storyboard.stop_s": scenario_end},
                        )
                    )
                for channel in _MOTION_CHANNELS:
                    names = [n for n, c in event.actions if c == channel]
                    if len(names) > 1:
                        findings.append(
                            _mk(
                                "STB-003",
                                f"Event '{event.name}' starts "
                                f"{len(names)} {channel} actions "
                                f"simultaneously ({', '.join(names)}): they "
                                "contend for the same control channel on the "
                                "same actor.",
                                scenario, event.label,
                                {"event.channel": channel,
                                 "event.actions": names},
                            )
                        )
                findings.extend(_parameter_findings(scenario, event))
    return findings


def _parameter_findings(scenario: Scenario, event: object) -> list[Finding]:
    findings: list[Finding] = []
    from physcheck.ir.model import EventIR

    assert isinstance(event, EventIR)
    trigger = event.start_trigger
    if trigger is None:
        return findings
    for cond in trigger.conditions:
        if cond.kind != "parameter" or cond.rule not in _NUMERIC_RULES:
            continue
        declared = scenario.parameters.get((cond.parameter_ref or "").lstrip("$"))
        for side, raw in (("comparison", cond.compare_value), ("declared", declared)):
            if raw is None:
                continue
            try:
                float(raw)
            except ValueError:
                findings.append(
                    _mk(
                        "STB-007",
                        f"Condition '{cond.label}' compares parameter "
                        f"'{cond.parameter_ref}' with rule '{cond.rule}', "
                        f"but the {side} value {raw!r} is not numeric — the "
                        "comparison is undefined.",
                        scenario, event.label,
                        {"condition.rule": cond.rule, "condition.value": raw},
                    )
                )
                break
    return findings
