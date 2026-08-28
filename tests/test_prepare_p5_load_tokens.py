from __future__ import annotations

from uuid import UUID

import jwt
import pytest

from app.config import settings
from scripts.prepare_p5_load_tokens import attach_tokens

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_attach_tokens_preserves_credentials_and_scopes_token_to_tenant():
    credentials = [{"email": "load@example.invalid", "password": "secret"}]
    result = attach_tokens(
        credentials,
        tenant_id=TENANT_ID,
        active_emails={"load@example.invalid"},
    )

    assert result[0]["email"] == credentials[0]["email"]
    assert result[0]["password"] == credentials[0]["password"]
    payload = jwt.decode(
        result[0]["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["sub"] == "load@example.invalid"
    assert payload["p5_load_test"] is True


def test_attach_tokens_rejects_users_outside_selected_tenant():
    with pytest.raises(ValueError, match="not active in tenant"):
        attach_tokens(
            [{"email": "wrong@example.invalid", "password": "secret"}],
            tenant_id=TENANT_ID,
            active_emails={"load@example.invalid"},
        )
