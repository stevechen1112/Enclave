import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services import deployment_mode


class _SessionStub:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_runtime_profile_falls_back_when_database_is_unavailable(monkeypatch):
    session = _SessionStub()
    monkeypatch.setattr(deployment_mode, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        deployment_mode,
        "resolve_runtime_profiles",
        lambda _db: (_ for _ in ()).throw(SQLAlchemyError("database unavailable")),
    )

    result = deployment_mode.resolve_runtime_profiles_no_db()

    assert result["mode"] == deployment_mode.DEPLOYMENT_MODE_NOGPU
    assert session.closed is True


def test_runtime_profile_does_not_hide_programming_errors(monkeypatch):
    session = _SessionStub()
    monkeypatch.setattr(deployment_mode, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        deployment_mode,
        "resolve_runtime_profiles",
        lambda _db: (_ for _ in ()).throw(ValueError("invalid profile")),
    )

    with pytest.raises(ValueError, match="invalid profile"):
        deployment_mode.resolve_runtime_profiles_no_db()

    assert session.closed is True
