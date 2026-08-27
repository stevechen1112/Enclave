from __future__ import annotations

from pathlib import Path

import yaml

from app.services.resilience_gate import REQUIRED_ALERTS

ROOT = Path(__file__).resolve().parents[1]


def test_every_alert_has_fire_and_recover_case():
    rules = yaml.safe_load(
        (ROOT / "monitoring" / "alert_rules.yml").read_text(encoding="utf-8")
    )
    declared = {
        rule["alert"]
        for group in rules["groups"]
        for rule in group["rules"]
        if rule.get("alert")
    }
    tests = yaml.safe_load(
        (ROOT / "monitoring" / "alert_rules.test.yml").read_text(encoding="utf-8")
    )["tests"]
    checks = [check for case in tests for check in case["alert_rule_test"]]
    fired = {check["alertname"] for check in checks if check.get("exp_alerts")}
    recovered = {
        check["alertname"] for check in checks if check.get("exp_alerts") == []
    }
    assert declared == REQUIRED_ALERTS
    assert fired == declared
    assert recovered == declared
