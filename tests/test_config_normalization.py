import pytest
from pydantic import ValidationError

from app.config import Settings


def test_source_verify_mode_is_trimmed_and_normalized():
    configured = Settings(_env_file=None, SOURCE_VERIFY_MODE="  ShAdOw  ")

    assert configured.SOURCE_VERIFY_MODE == "shadow"


def test_source_verify_mode_rejects_unknown_value():
    with pytest.raises(ValidationError, match="SOURCE_VERIFY_MODE"):
        Settings(_env_file=None, SOURCE_VERIFY_MODE="audit-ish")


def test_demo_login_requires_explicit_tenant_uuid():
    from app.demo.manifest import DEMO_TENANT_ID

    with pytest.raises(ValidationError, match="DEMO_TENANT_ID"):
        Settings(_env_file=None, DEMO_LOGIN_ENABLED=True, DEMO_TENANT_ID="")

    configured = Settings(
        _env_file=None,
        DEMO_LOGIN_ENABLED=True,
        DEMO_TENANT_ID=str(DEMO_TENANT_ID),
        FIXED_FORM_ENABLED=True,
        KNOWHOW_CARD_ENABLED=True,
    )
    assert configured.DEMO_LOGIN_ENABLED is True


def test_demo_login_requires_complete_demo_capabilities():
    from app.demo.manifest import DEMO_TENANT_ID

    with pytest.raises(ValidationError, match="FIXED_FORM_ENABLED"):
        Settings(
            _env_file=None,
            DEMO_LOGIN_ENABLED=True,
            DEMO_TENANT_ID=str(DEMO_TENANT_ID),
            FIXED_FORM_ENABLED=False,
            KNOWHOW_CARD_ENABLED=False,
            MODULE_ROUTER_ENABLED=True,
        )

    with pytest.raises(ValidationError, match="KNOWHOW_CARD_ENABLED"):
        Settings(
            _env_file=None,
            DEMO_LOGIN_ENABLED=True,
            DEMO_TENANT_ID=str(DEMO_TENANT_ID),
            FIXED_FORM_ENABLED=True,
            KNOWHOW_CARD_ENABLED=False,
            MODULE_ROUTER_ENABLED=True,
        )

    with pytest.raises(ValidationError, match="MODULE_ROUTER_ENABLED"):
        Settings(
            _env_file=None,
            DEMO_LOGIN_ENABLED=True,
            DEMO_TENANT_ID=str(DEMO_TENANT_ID),
            FIXED_FORM_ENABLED=True,
            KNOWHOW_CARD_ENABLED=True,
            MODULE_ROUTER_ENABLED=False,
        )


def test_demo_login_rejects_noncanonical_tenant_uuid():
    import uuid

    with pytest.raises(ValidationError, match="canonical synthetic Demo"):
        Settings(
            _env_file=None,
            DEMO_LOGIN_ENABLED=True,
            DEMO_TENANT_ID=str(uuid.uuid4()),
        )


def test_demo_login_rejects_noncanonical_admin_identity():
    from app.demo.manifest import DEMO_TENANT_ID

    with pytest.raises(ValidationError, match="canonical internal Demo admin"):
        Settings(
            _env_file=None,
            DEMO_LOGIN_ENABLED=True,
            DEMO_TENANT_ID=str(DEMO_TENANT_ID),
            DEMO_ADMIN_EMAIL="owner@example.com",
        )
