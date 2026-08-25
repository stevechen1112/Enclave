#!/usr/bin/env python3
"""Retired: external sidecar content may not be seeded into the public Demo."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "Disabled: the public Demo tenant is synthetic-only. "
        "Use a separately authenticated staging tenant for sidecar integration tests.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
