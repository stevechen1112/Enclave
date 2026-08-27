from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.main import health_check
from app.services.runtime_readiness import database_readiness


def test_database_readiness_publishes_ready():
    connection = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = connection
    with (
        patch("app.db.session.readiness_engine.connect", return_value=context),
        patch("app.middleware.metrics.set_dependency_ready") as metric,
    ):
        assert database_readiness() is True
    connection.execute.assert_called_once()
    metric.assert_called_once_with("database", True)


def test_database_readiness_fails_closed_without_error_details():
    with (
        patch(
                "app.db.session.readiness_engine.connect",
                side_effect=SQLAlchemyError("secret DSN"),
        ),
        patch("app.middleware.metrics.set_dependency_ready") as metric,
    ):
        assert database_readiness() is False
    metric.assert_called_once_with("database", False)


def test_health_endpoint_returns_sanitized_503_when_database_is_unavailable():
    with patch(
        "app.services.runtime_readiness.database_readiness", return_value=False
    ):
        response = health_check()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert b'"status":"unavailable"' in response.body
    assert b'"database":"unavailable"' in response.body
    assert b"secret" not in response.body


def test_health_endpoint_returns_ready_dependency_state():
    with patch("app.services.runtime_readiness.database_readiness", return_value=True):
        response = health_check()

    assert response["status"] == "ok"
    assert response["dependencies"] == {"database": "ready"}
