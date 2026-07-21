"""odd-pilot: ODD-aware campaign copilot for scenario-based ADS testing.

Implemented: lint (physcheck), model (learned operational BN), assess (PWCC
adequacy with risk-calibrated stopping rule), gaps (ranked residual mass),
plan (gap-targeted generation with the physcheck gate), report (SOTIF-style
evidence artifact), loop (executor-driven orchestration to adequacy), conform (L5 ODD
verdicts).
Roadmap: init/config scaffolding.
"""

__version__ = "0.6.0"
