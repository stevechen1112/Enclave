from app.services.release_metadata import (
    get_public_release_metadata,
    get_release_metadata,
)


class _Result:
    def scalars(self):
        return ["phase_p0_001"]


class _Db:
    def execute(self, _statement):
        return _Result()


def test_release_metadata_is_unidentifiable_without_build_identity(monkeypatch):
    for name in (
        "ENCLAVE_RELEASE_ID",
        "ENCLAVE_SOURCE_COMMIT",
        "ENCLAVE_SOURCE_DIRTY",
        "ENCLAVE_BUILD_TIME",
        "ENCLAVE_SCHEMA_HEAD",
        "ENCLAVE_ROUTE_CONTRACT_HASH",
    ):
        monkeypatch.delenv(name, raising=False)

    assert get_release_metadata()["identifiable"] is False


def test_release_metadata_is_identifiable_when_required_fields_are_injected(
    monkeypatch,
):
    values = {
        "ENCLAVE_RELEASE_ID": "release-42",
        "ENCLAVE_SOURCE_COMMIT": "a" * 40,
        "ENCLAVE_SOURCE_DIRTY": "false",
        "ENCLAVE_BUILD_TIME": "2026-08-27T10:00:00Z",
        "ENCLAVE_SCHEMA_HEAD": "phase_p0_001",
        "ENCLAVE_ROUTE_CONTRACT_HASH": "b" * 64,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    metadata = get_release_metadata()
    assert metadata["identifiable"] is True
    assert metadata["release_id"] == "release-42"
    assert metadata["schema_head"] == "phase_p0_001"


def test_public_release_metadata_excludes_image_digests(monkeypatch):
    monkeypatch.setenv("ENCLAVE_BACKEND_IMAGE_DIGEST", "sha256:backend")
    monkeypatch.setenv("ENCLAVE_FRONTEND_IMAGE_DIGEST", "sha256:frontend")

    public = get_public_release_metadata()

    assert "backend_image_digest" not in public
    assert "frontend_image_digest" not in public


def test_operations_release_compares_database_schema_head(monkeypatch):
    from app.api.v1.endpoints.operations import release_metadata

    values = {
        "ENCLAVE_RELEASE_ID": "release-42",
        "ENCLAVE_SOURCE_COMMIT": "a" * 40,
        "ENCLAVE_SOURCE_DIRTY": "false",
        "ENCLAVE_BUILD_TIME": "2026-08-27T10:00:00Z",
        "ENCLAVE_SCHEMA_HEAD": "phase_p0_001",
        "ENCLAVE_ROUTE_CONTRACT_HASH": "b" * 64,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    metadata = release_metadata(current_user=object(), db=_Db())

    assert metadata["database_schema_heads"] == ["phase_p0_001"]
    assert metadata["schema_matches"] is True
