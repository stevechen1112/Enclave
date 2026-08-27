from scripts.freeze_deployment_manifest import deployment_files, deployment_manifest_id


def test_deployment_manifest_excludes_workspace_artifacts_and_test_corpora():
    records = {
        path.as_posix()
        for paths in deployment_files().values()
        for path in paths
    }
    assert records
    assert not any("/artifacts/" in path or "/test-materials/" in path or "/testdata/" in path for path in records)
    assert any(path.endswith("app/main.py") for path in records)
    assert any(path.endswith("frontend/src/App.tsx") for path in records)
    assert any(path.endswith("requirements.lock.txt") for path in records)
    assert any(path.endswith("docker/gateway.Dockerfile") for path in records)


def test_backend_docker_context_uses_strict_runtime_allowlist():
    # deployment_files returns absolute paths rooted in the repository; resolve
    # the file from the manifest instead of relying on the process CWD.
    dockerignore = next(
        path for path in deployment_files()["backend"] if path.name == ".dockerignore"
    )
    rules = dockerignore.read_text(encoding="utf-8").splitlines()
    strict_index = rules.index("*")
    strict_rules = set(rules[strict_index + 1 :])
    assert {
        "!.dockerignore",
        "!Dockerfile",
        "!requirements.txt",
        "!requirements.lock.txt",
        "!alembic.ini",
        "!celery_worker.py",
        "!app/**",
        "!docker/**",
        "!configs/**",
    } <= strict_rules


def test_manifest_id_is_stable_across_image_builds_and_changes_with_source():
    records = [{"group": "backend", "path": "app/main.py", "sha256": "a" * 64, "bytes": 10}]
    same = [dict(records[0])]
    changed = [dict(records[0], sha256="b" * 64)]
    assert deployment_manifest_id(records) == deployment_manifest_id(same)
    assert deployment_manifest_id(records) != deployment_manifest_id(changed)
