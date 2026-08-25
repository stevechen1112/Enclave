#!/usr/bin/env python3
"""Retired legacy helper; user creation must use the supported admin workflow."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "Disabled: this legacy script created a fixed-password user. "
        "Use the authenticated tenant administration workflow instead.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
