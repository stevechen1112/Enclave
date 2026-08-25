#!/usr/bin/env python3
"""Retired compatibility entry point for heuristic E2E cleanup."""

from cleanup_prod_e2e import main

if __name__ == "__main__":
    raise SystemExit(main())
