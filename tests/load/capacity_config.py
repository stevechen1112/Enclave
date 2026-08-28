"""Shared P5 load-test configuration with no Locust dependency."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "config" / "capacity_profiles.json"


def load_spec() -> dict[str, Any]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def spec_sha256() -> str:
    spec = load_spec()
    canonical = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def selected_profile() -> tuple[str, dict[str, Any]]:
    spec = load_spec()
    name = os.getenv("CAPACITY_PROFILE", "standard").strip().lower()
    if name not in spec["profiles"]:
        raise ValueError(f"unknown CAPACITY_PROFILE: {name}")
    return name, spec["profiles"][name]


def target_load() -> dict[str, int | float]:
    spec = load_spec()
    _, profile = selected_profile()
    execution_class = os.getenv("LOAD_TEST_CLASS", "capacity").strip().lower()
    if execution_class not in {"capacity", "soak"}:
        raise ValueError(f"unknown LOAD_TEST_CLASS: {execution_class}")
    multiplier = float(
        os.getenv("LOAD_MULTIPLIER", str(spec["test_policy"]["peak_multiplier"]))
    )
    minimum = (
        1.0
        if execution_class == "soak"
        else float(spec["test_policy"]["peak_multiplier"])
    )
    if multiplier < minimum:
        raise ValueError(
            f"LOAD_MULTIPLIER is below the {execution_class} minimum ({minimum:g})"
        )
    return {
        key: int(value * multiplier) if isinstance(value, int) else value * multiplier
        for key, value in profile["expected_peak"].items()
    }


def fixture_paths() -> dict[str, Path]:
    return {
        "document": Path(os.getenv("LOAD_DOCUMENT_FIXTURE_PATH", "")),
        "audio": Path(os.getenv("LOAD_AUDIO_FIXTURE_PATH", "")),
        "video": Path(os.getenv("LOAD_VIDEO_FIXTURE_PATH", "")),
    }


def validate_full_scenario_environment() -> list[str]:
    errors: list[str] = []
    for name in (
        "LOAD_TEST_USER_PASSWORD",
        "LOAD_TEST_ADMIN_PASSWORD",
        "LOAD_TEST_SUPERUSER_PASSWORD",
    ):
        if not os.getenv(name):
            errors.append(f"{name} is required")
    if os.getenv("P5_FULL_SCENARIO", "false").lower() in {"1", "true", "yes"}:
        for kind, path in fixture_paths().items():
            if not str(path) or not path.is_file():
                errors.append(f"valid LOAD_{kind.upper()}_FIXTURE_PATH is required")
    return errors
