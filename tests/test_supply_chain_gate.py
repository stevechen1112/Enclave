from __future__ import annotations

from pathlib import Path

from scripts.supply_chain_gate import evaluate


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_tree(root: Path) -> None:
    digest = "a" * 64
    action = "b" * 40
    _write(
        root,
        ".github/workflows/ci.yml",
        f"steps:\n  - uses: actions/checkout@{action} # v6\n  - image: redis:7@sha256:{digest}\n",
    )
    _write(root, "Dockerfile", f"FROM python:3@sha256:{digest}\n")
    _write(root, "frontend/Dockerfile", f"FROM node:22@sha256:{digest}\n")
    _write(root, "docker/gateway.Dockerfile", f"FROM nginx:1@sha256:{digest}\n")
    _write(
        root,
        "docker-compose.prod.yml",
        f"services:\n  db:\n    image: postgres:16@sha256:{digest}\n",
    )
    _write(
        root,
        "compose/sidecars.yml",
        f"services:\n  redis:\n    image: redis:7@sha256:{digest}\n",
    )
    _write(root, "requirements.lock.txt", "fastapi==0.141.1\n")
    _write(root, "requirements-test.lock.txt", "pytest==9.1.1\n")
    _write(root, ".dockerignore", "*\n!requirements.lock.txt\n")
    _write(root, "frontend/package-lock.json", '{"lockfileVersion": 3}')


def test_supply_chain_gate_accepts_sha_and_digest_pins(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    assert evaluate(tmp_path, tracked_paths=[])["status"] == "PASS"


def test_supply_chain_gate_rejects_floating_inputs(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    _write(
        tmp_path, ".github/workflows/ci.yml", "steps:\n  - uses: actions/checkout@v6\n"
    )
    _write(tmp_path, "Dockerfile", "FROM python:3.13-slim\n")
    _write(tmp_path, "requirements.lock.txt", "fastapi>=0.141.1\n")
    report = evaluate(tmp_path, tracked_paths=[])
    assert report["status"] == "FAIL"
    assert any(error.startswith("action_not_sha_pinned") for error in report["errors"])
    assert any(
        error.startswith("base_image_not_digest_pinned") for error in report["errors"]
    )
    assert any(error.startswith("python_lock_unpinned") for error in report["errors"])
