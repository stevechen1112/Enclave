"""Contracts that keep tenant audit views useful without erasing system evidence."""

import inspect

from app.api.v1.endpoints.audit import get_audit_logs
from app.crud.crud_audit import get_audit_logs as get_audit_rows


def test_business_audit_feed_hides_compatibility_telemetry_by_default():
    """Legacy telemetry remains opt-in instead of flooding the Owner's default feed."""
    assert inspect.signature(get_audit_logs).parameters["include_system_events"].default is False
    assert inspect.signature(get_audit_rows).parameters["include_system_events"].default is False


def test_business_audit_feed_can_explicitly_include_system_events():
    """The evidence is retained and can be requested for diagnostics."""
    parameter = inspect.signature(get_audit_logs).parameters["include_system_events"]
    assert parameter.annotation is bool
