"""odd-pilot CLI skeleton.

Only ``odd-pilot lint`` works today (it delegates to physcheck). All other
subcommands are stubs for the roadmap components (model, assess, gaps, plan,
report, conform, loop, init, config).
"""

from __future__ import annotations

import sys

_STUBS = (
    "init",
    "config",
    "model",
    "assess",
    "gaps",
    "plan",
    "report",
    "conform",
    "loop",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("subcommands: lint | " + " | ".join(_STUBS) + "  (stubs)")
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "lint":
        from physcheck.cli import main as physcheck_main

        return physcheck_main(["lint", *rest])
    if cmd in _STUBS:
        raise NotImplementedError(
            f"odd-pilot {cmd!r} is a roadmap stub (v0.2+); only physcheck (lint) "
            "is implemented in v0.1 — see the design brief."
        )
    print(f"odd-pilot: unknown command {cmd!r}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
