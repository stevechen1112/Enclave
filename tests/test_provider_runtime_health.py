from app.services import provider_runtime_health as health
from app.api.deps_permissions import require_admin
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.company import router as company_router
from app.services.llm_client import LLMClient


def _profiles():
    return {
        "main": {"provider": "openai", "model": "main-model"},
        "internal": {"provider": "gemini", "model": "internal-model"},
        "scan": {"provider": "gemini", "model": "scan-model"},
        "embedding": {"provider": "ollama", "model": "embed-model"},
    }


def test_provider_configuration_never_returns_secret_values(monkeypatch):
    monkeypatch.setattr(health, "resolve_runtime_profiles_no_db", _profiles)
    monkeypatch.setattr(health.settings, "OPENAI_API_KEY", "do-not-return-openai")
    monkeypatch.setattr(health.settings, "GEMINI_API_KEY", "do-not-return-gemini")
    monkeypatch.setattr(health.settings, "VOICE_STT_ENABLED", True)
    monkeypatch.setattr(health.settings, "VOICE_TTS_ENABLED", True)
    monkeypatch.setenv("CLOUD_OCR_PROVIDER", "gemini")
    monkeypatch.setenv("CLOUD_OCR_MODEL", "ocr-model")

    result = health.provider_configuration()

    assert {item["role"] for item in result} == {
        "main_llm", "internal_llm", "scan_llm", "embedding",
        "voice_roundtrip", "long_audio", "cloud_ocr",
    }
    rendered = str(result)
    assert "do-not-return-openai" not in rendered
    assert "do-not-return-gemini" not in rendered
    assert all("credential_configured" in item for item in result)


def test_required_probe_passes_only_when_every_role_returns_content(monkeypatch):
    configs = [
        {
            "role": role,
            "label": role,
            "provider": "fake",
            "model": "fake-model",
            "enabled": True,
            "credential_configured": True,
            "required": True,
        }
        for role in (
            "main_llm", "internal_llm", "scan_llm", "embedding",
            "voice_roundtrip", "long_audio", "cloud_ocr",
        )
    ]
    monkeypatch.setattr(health, "provider_configuration", lambda: configs)
    monkeypatch.setattr(health, "_probe_llm", lambda profile: "PROVIDER_OK")
    monkeypatch.setattr(health, "_probe_embedding", lambda: [0.1, 0.2])
    monkeypatch.setattr(health, "_probe_voice_roundtrip", lambda: "語音成功")
    monkeypatch.setattr(health, "_probe_long_audio", lambda: "長音檔成功")
    monkeypatch.setattr(health, "_probe_cloud_ocr", lambda: "OCR 8246")

    report = health.probe_required_providers()

    assert report["status"] == "pass"
    assert report["passed"] == report["total"] == 7
    assert "probed_at" in report
    assert "release_bound" in report
    assert "source_commit" in report["release"]


def test_required_probe_fails_closed_and_sanitizes_provider_error(monkeypatch):
    configs = [
        {
            "role": role,
            "label": role,
            "provider": "fake",
            "model": "fake-model",
            "enabled": True,
            "credential_configured": True,
            "required": True,
        }
        for role in (
            "main_llm", "internal_llm", "scan_llm", "embedding",
            "voice_roundtrip", "long_audio", "cloud_ocr",
        )
    ]
    monkeypatch.setattr(health, "provider_configuration", lambda: configs)
    monkeypatch.setattr(health, "_probe_llm", lambda profile: "PROVIDER_OK")
    monkeypatch.setattr(health, "_probe_embedding", lambda: [0.1])
    monkeypatch.setattr(health, "_probe_voice_roundtrip", lambda: "語音成功")
    monkeypatch.setattr(health, "_probe_long_audio", lambda: "長音檔成功")

    def fail_ocr():
        raise RuntimeError("https://provider.invalid key=super-secret response body")

    monkeypatch.setattr(health, "_probe_cloud_ocr", fail_ocr)

    report = health.probe_required_providers()

    assert report["status"] == "fail"
    failed = next(item for item in report["results"] if item["role"] == "cloud_ocr")
    assert failed["detail"] == "Provider 呼叫失敗（RuntimeError）"
    assert "super-secret" not in str(report)


def test_provider_probe_is_explicit_post_and_tenant_admin_only():
    route = next(
        item for item in admin_router.routes
        if getattr(item, "path", "") == "/system/provider-health/probe"
    )
    assert route.methods == {"POST"}
    assert require_admin in {dependency.call for dependency in route.dependant.dependencies}


def test_company_provider_probe_is_explicit_post_and_tenant_admin_only():
    """Tenant-facing health uses /company, never the IP-whitelisted /admin surface."""
    route = next(
        item for item in company_router.routes
        if getattr(item, "path", "") == "/system/provider-health/probe"
    )
    assert route.methods == {"POST"}
    assert require_admin in {dependency.call for dependency in route.dependant.dependencies}


def test_llm_health_check_rejects_empty_success(monkeypatch):
    client = object.__new__(LLMClient)
    client.provider = "fake"
    client._model = "fake-model"
    monkeypatch.setattr(client, "complete", lambda *args, **kwargs: "")

    result = client.health_check()

    assert result["status"] == "error"
    assert "空白" in result["error"]


def test_llm_probe_reserves_visible_output_budget(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def complete(self, *args, **kwargs):
            captured["complete"] = kwargs
            return "PROVIDER_OK"

    monkeypatch.setattr(health, "resolve_runtime_profiles_no_db", lambda: {
        "internal": {"provider": "gemini", "model": "gemini-3.6-flash"},
    })
    monkeypatch.setattr("app.services.llm_client.LLMClient", FakeClient)

    assert health._probe_llm("internal") == "PROVIDER_OK"
    assert captured["complete"]["max_tokens"] >= 128
