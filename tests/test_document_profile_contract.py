from app.services.document_parser import SUPPORTED_FORMATS
from app.services.document_profile import FORMAT_CAPABILITIES, build_document_profile


def test_parser_canonical_formats_are_all_known_to_capability_profiler():
    canonical_types = set(SUPPORTED_FORMATS.values()) - {"pdf"}
    assert canonical_types <= set(FORMAT_CAPABILITIES)
    assert {"pdf_text", "pdf_scan"} <= set(FORMAT_CAPABILITIES)
    for file_type in set(SUPPORTED_FORMATS.values()):
        profile = build_document_profile(file_type=file_type, text="verified content")
        assert profile.format_family != "unknown", file_type
        assert profile.support_level != "unsupported", file_type


def test_parser_markdown_name_is_answer_ready_after_successful_processing():
    profile = build_document_profile(
        file_type=SUPPORTED_FORMATS[".md"],
        text="# 復歸步驟\n步驟 1：確認壓力歸零。",
    )
    assert profile.format_family == "markdown"
    assert profile.answer_ready is True
    assert profile.readiness["procedure"] is True
    assert profile.profiler_version == "1.1"
