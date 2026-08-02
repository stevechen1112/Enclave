"""C1 — connector name map must match PipesHub's Connectors enum values."""
from __future__ import annotations

from app.gateway.adapters.pipeshub_http import _CONNECTOR_NAME_MAP

# Canonical values from pipeshub-ai backend app/config/constants/arangodb.py Connectors.
PIPESHUB_CONNECTOR_VALUES = {
    "DRIVE", "DRIVE WORKSPACE", "GMAIL", "GMAIL WORKSPACE", "CALENDAR",
    "ONEDRIVE", "SHAREPOINT ONLINE", "OUTLOOK", "OUTLOOK PERSONAL",
    "OUTLOOK CALENDAR", "MICROSOFT TEAMS", "NOTION", "SLACK", "SLACK WORKSPACE",
    "KB", "CONFLUENCE", "CONFLUENCE DATA CENTER", "JIRA", "BOX", "NEXTCLOUD",
    "DROPBOX", "WEB", "BOOKSTACK", "GITHUB", "SERVICENOW", "SALESFORCE",
    "S3", "MINIO", "GCS", "AZURE BLOB", "AZURE FILES", "LINEAR", "ZAMMAD",
    "ZOOM", "GITLAB", "SNOWFLAKE", "POSTGRESQL", "MARIADB", "RSS", "LOCAL_FS",
}


def test_all_mapped_names_are_valid_pipeshub_connectors():
    for enclave_type, pipeshub_name in _CONNECTOR_NAME_MAP.items():
        assert pipeshub_name in PIPESHUB_CONNECTOR_VALUES, (
            f"{enclave_type} maps to unknown PipesHub connector {pipeshub_name!r}"
        )


def test_bookstack_is_mapped():
    # C3 depends on this: BookStack is the permission-aware search source.
    assert _CONNECTOR_NAME_MAP.get("bookstack") == "BOOKSTACK"


def test_no_stale_names():
    # Regression guard against the pre-C1 typos.
    assert "NAS" not in _CONNECTOR_NAME_MAP.values()
    assert "SHAREPOINT" not in _CONNECTOR_NAME_MAP.values()  # must be SHAREPOINT ONLINE
    assert "TEAMS" not in _CONNECTOR_NAME_MAP.values()       # must be MICROSOFT TEAMS
