from __future__ import annotations

import pytest

from app.services.safe_web_fetch import UnsafeSourceURL, assert_public_http_url


def _resolve_to(address: str):
    return lambda *_args: [(2, 1, 6, "", (address, 443))]


def test_public_web_url_accepts_only_public_resolution():
    assert (
        assert_public_http_url(
            "https://knowledge.example/path", resolver=_resolve_to("93.184.216.34")
        )
        == "https://knowledge.example/path"
    )

    for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"):
        with pytest.raises(UnsafeSourceURL):
            assert_public_http_url(
                "https://knowledge.example/path", resolver=_resolve_to(address)
            )


def test_public_web_url_rejects_credentials_and_localhost():
    for value in (
        "file:///etc/passwd",
        "http://localhost/admin",
        "https://user:secret@example.com/",
    ):
        with pytest.raises(UnsafeSourceURL):
            assert_public_http_url(value, resolver=_resolve_to("93.184.216.34"))
