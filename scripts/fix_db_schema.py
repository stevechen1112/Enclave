#!/usr/bin/env python3
"""Retired compatibility entry point for unsafe direct schema repair."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "Direct ALTER TABLE repair is disabled. "
        "Inspect the Alembic heads, take a backup, then run `alembic upgrade head` "
        "through the documented deployment procedure.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
