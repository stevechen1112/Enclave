from app.services.text_locale import normalize_content_text


def test_zh_tw_normalization_is_deterministic_and_preserves_numbers():
    source = "员工责任制的压力是 6.5 BAR"
    normalized = normalize_content_text(source, locale="zh-TW")
    assert normalized == "員工責任制的壓力是 6.5 BAR"
    assert normalize_content_text(normalized, locale="zh-TW") == normalized


def test_non_chinese_locale_only_applies_unicode_normalization():
    assert normalize_content_text("ＡＸ－１７", locale="en-US") == "AX-17"
