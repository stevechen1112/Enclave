from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.license_policy_gate import evaluate


class _Distribution:
    version = "1.0"

    def __init__(self, name: str, licence: str):
        self.metadata = {"Name": name, "License": licence}


def test_license_gate_requires_exception(tmp_path: Path) -> None:
    policy = tmp_path / "exceptions.json"
    policy.write_text('{"exceptions": []}', encoding="utf-8")
    with patch(
        "scripts.license_policy_gate.importlib.metadata.distributions",
        return_value=[_Distribution("Risky", "AGPL-3.0")],
    ):
        report = evaluate(policy, today=date(2026, 8, 27), allowed_names={"risky"})
    assert report["status"] == "FAIL"


def test_license_gate_accepts_owned_unexpired_exception(tmp_path: Path) -> None:
    policy = tmp_path / "exceptions.json"
    policy.write_text(
        json.dumps(
            {
                "exceptions": [
                    {
                        "package": "Risky",
                        "owner": "legal",
                        "reason": "review",
                        "ticket": "LIC-1",
                        "expires_at": "2026-09-01",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with patch(
        "scripts.license_policy_gate.importlib.metadata.distributions",
        return_value=[_Distribution("Risky", "GNU Affero General Public License")],
    ):
        report = evaluate(policy, today=date(2026, 8, 27), allowed_names={"risky"})
    assert report["status"] == "PASS"
