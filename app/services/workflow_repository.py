"""Workflow persistence facade over the MKA-era compatibility implementation.

New core and application code depends on this deliberately narrow surface. The
underlying repository remains during the compatibility window because approval
side effects for existing know-how records still need an application hook in A3.
"""

from __future__ import annotations

from typing import Any

from app.services.mka_persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKAPersistenceError,
    MKARepository,
    approval_to_dict,
    form_definition_to_dict,
    form_instance_to_dict,
)


WorkflowPersistenceError = MKAPersistenceError
WorkflowNotFoundError = MKANotFoundError
WorkflowConflictError = MKAConflictError
WorkflowForbiddenError = MKAForbiddenError


class WorkflowRepository:
    """Closed form and approval facade; no know-how methods are exposed."""

    _EXPORT_FORMATS = MKARepository._EXPORT_FORMATS

    def __init__(self, db: Any):
        self._compat = MKARepository(db)

    def ensure_form_definitions(self, *args: Any, **kwargs: Any):
        return self._compat.ensure_form_definitions(*args, **kwargs)

    def list_form_definitions(self, *args: Any, **kwargs: Any):
        return self._compat.list_form_definitions(*args, **kwargs)

    def get_form_definition(self, *args: Any, **kwargs: Any):
        return self._compat.get_form_definition(*args, **kwargs)

    def validate_form_values(self, *args: Any, **kwargs: Any):
        return self._compat.validate_form_values(*args, **kwargs)

    def create_form_instance(self, *args: Any, **kwargs: Any):
        return self._compat.create_form_instance(*args, **kwargs)

    def get_form_instance(self, *args: Any, **kwargs: Any):
        return self._compat.get_form_instance(*args, **kwargs)

    def patch_form_instance(self, *args: Any, **kwargs: Any):
        return self._compat.patch_form_instance(*args, **kwargs)

    def calculate_form(self, *args: Any, **kwargs: Any):
        return self._compat.calculate_form(*args, **kwargs)

    def validate_form(self, *args: Any, **kwargs: Any):
        return self._compat.validate_form(*args, **kwargs)

    def submit_form(self, *args: Any, **kwargs: Any):
        return self._compat.submit_form(*args, **kwargs)

    def assert_form_exportable(self, *args: Any, **kwargs: Any):
        return self._compat.assert_form_exportable(*args, **kwargs)

    def export_form(self, *args: Any, **kwargs: Any):
        return self._compat.export_form(*args, **kwargs)

    def list_approvals(self, *args: Any, **kwargs: Any):
        return self._compat.list_approvals(*args, **kwargs)

    def get_approval(self, *args: Any, **kwargs: Any):
        return self._compat.get_approval(*args, **kwargs)

    def get_pending_approval_for_object(self, *args: Any, **kwargs: Any):
        return self._compat.get_pending_approval_for_object(*args, **kwargs)

    def decide_approval(self, *args: Any, **kwargs: Any):
        return self._compat.decide_approval(*args, **kwargs)
