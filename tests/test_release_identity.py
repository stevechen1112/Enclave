from pathlib import Path

from scripts.release_identity import migration_heads, route_contract


def test_release_identity_has_exactly_one_schema_head():
    heads = migration_heads()
    assert len(heads) == 1
    assert heads[0]


def test_release_route_contract_is_unique_and_hashable():
    routes, contract_hash = route_contract()
    assert len(routes) == len(set(routes))
    assert "/knowledge/assets" in routes
    assert len(contract_hash) == 64


def test_frontend_runtime_image_preserves_release_labels():
    dockerfile = (
        Path(__file__).resolve().parents[1] / "frontend" / "Dockerfile"
    ).read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("FROM nginx:1.27-alpine", maxsplit=1)[1]

    assert "ARG VITE_SOURCE_COMMIT=unknown" in runtime_stage
    assert "org.opencontainers.image.revision=${VITE_SOURCE_COMMIT}" in runtime_stage
    assert "io.enclave.release-id=${VITE_RELEASE_ID}" in runtime_stage
