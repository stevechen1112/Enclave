import hashlib

from scripts.release_source_gate import scan_secret_types, verify_records


def _record(path, group="backend"):
    data = path.read_bytes()
    return {
        "group": group,
        "path": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def test_verify_records_accepts_exact_inventory(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("print('safe')\n", encoding="utf-8")

    assert verify_records(tmp_path, [_record(source)], ["source.py"]) == []


def test_verify_records_rejects_hash_drift_and_inventory_gap(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("before\n", encoding="utf-8")
    record = _record(source)
    source.write_text("after\n", encoding="utf-8")

    errors = verify_records(tmp_path, [record], ["source.py", "missing.py"])

    assert "manifest_record_hash_mismatch:source.py" in errors
    assert "manifest_record_size_mismatch:source.py" in errors
    assert "manifest_coverage_mismatch:missing=1,unexpected=0" in errors


def test_verify_records_rejects_wrong_deployment_group(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("safe\n", encoding="utf-8")

    errors = verify_records(tmp_path, [_record(source, group="frontend")], {"source.py": "backend"})

    assert errors == ["manifest_record_group_mismatch:source.py"]


def test_secret_scan_reports_type_without_exposing_value(tmp_path):
    source = tmp_path / "settings.txt"
    fake_value = "sk-" + "abcdefghijklmnopqrstuvwx"
    source.write_text(f"token={fake_value}", encoding="utf-8")

    findings = scan_secret_types(tmp_path, ["settings.txt"])

    assert findings == {"settings.txt": ["openai_key"]}
    assert fake_value not in repr(findings)


def test_secret_scan_skips_binary_files(tmp_path):
    source = tmp_path / "image.bin"
    source.write_bytes(b"\x00" + b"sk-" + b"abcdefghijklmnopqrstuvwx")

    assert scan_secret_types(tmp_path, ["image.bin"]) == {}


def test_secret_scan_rejects_compromised_value_without_storing_plaintext(tmp_path):
    source = tmp_path / "legacy.txt"
    compromised = "Demo" + "12345"
    source.write_text(f"credential={compromised}", encoding="utf-8")

    findings = scan_secret_types(tmp_path, ["legacy.txt"])

    assert findings == {"legacy.txt": ["compromised_credential"]}
    assert compromised not in repr(findings)
