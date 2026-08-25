from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps_permissions import (
    allow_all_authenticated,
    require_admin,
    require_knowhow_author,
)


def _user(*, role: str = "employee", superuser: bool = False):
    return SimpleNamespace(is_superuser=superuser, role=role)


def test_master_job_role_can_author_knowhow(monkeypatch):
    monkeypatch.setattr(
        "app.services.job_context.build_effective_job_context",
        lambda _db, _user: SimpleNamespace(active_job_role_keys=["master"]),
    )

    user = _user()
    assert require_knowhow_author(db=object(), current_user=user) is user


def test_newcomer_job_role_cannot_author_knowhow(monkeypatch):
    monkeypatch.setattr(
        "app.services.job_context.build_effective_job_context",
        lambda _db, _user: SimpleNamespace(active_job_role_keys=["newcomer"]),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_knowhow_author(db=object(), current_user=_user())

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_tenant_administrators_can_author_knowhow(role):
    user = _user(role=role)
    assert require_knowhow_author(db=object(), current_user=user) is user


def test_knowhow_routes_keep_read_write_and_admin_boundaries_separate():
    from app.api.v1.endpoints.knowhow import router

    dependencies = {
        (route.path, next(iter(route.methods))): {
            dependency.call for dependency in route.dependant.dependencies
        }
        for route in router.routes
    }

    assert allow_all_authenticated in dependencies[("/knowhow", "GET")]
    assert allow_all_authenticated in dependencies[("/knowhow/{knowhow_id}", "GET")]
    assert require_knowhow_author in dependencies[("/knowhow", "POST")]
    assert require_knowhow_author in dependencies[("/knowhow/{knowhow_id}", "PATCH")]
    assert require_knowhow_author in dependencies[("/knowhow/{knowhow_id}/submit", "POST")]
    assert require_admin in dependencies[("/knowhow/{knowhow_id}/approve", "POST")]
    assert require_admin in dependencies[("/knowhow/{knowhow_id}/retire", "POST")]
