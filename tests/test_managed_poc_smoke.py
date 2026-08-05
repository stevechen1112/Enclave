"""managed_poc_smoke 腳本結構測試（不連線）。"""
import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "managed_poc_smoke.py"
    spec = importlib.util.spec_from_file_location("managed_poc_smoke", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_smoke_class_logs_results():
    mod = _load_module()
    smoke = mod.ManagedPocSmoke(skip_auth=True, skip_upload=True, skip_chat=True)
    smoke.log("test", True, "ok")
    smoke.log("test2", False, "bad")
    assert len(smoke.results) == 2
    assert smoke.results[0]["passed"] is True
    assert smoke.results[1]["passed"] is False
