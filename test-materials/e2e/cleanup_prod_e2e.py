#!/usr/bin/env python3
"""Retired: production data must never be cleaned by test heuristics."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "Disabled. Reset only the canonical synthetic tenant with "
        "`python scripts/demo_tenant.py reset --confirm-reset <canonical-uuid>`.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
