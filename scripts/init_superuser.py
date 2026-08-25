#!/usr/bin/env python3
"""Create the configured organization owner through the supported local path.

This compatibility entry point intentionally performs no SSH or remote mutation.
Production operators must inject FIRST_SUPERUSER_* through the deployment secret
store and execute this inside the intended application container.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.initial_data import init_db


def main() -> int:
    init_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
