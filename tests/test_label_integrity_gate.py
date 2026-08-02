"""The label-integrity gate must actually catch the defect it was written for."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eval_label_integrity", ROOT / "scripts" / "eval_label_integrity.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

# Exactly the shape parse_pipeline.py had before A1 removed it.
REGRESSION_SNIPPET = '''
    if not chunks:
        meta_engine = "ragflow/deepdoc"
    else:
        meta_engine = "ragflow/deepdoc"
    artifact = ParseArtifact(
        ocr_used=route == ParseRoute.RAGFLOW_DEEPDOC,
    )
'''


def test_detects_hardcoded_deepdoc_label():
    assert gate.HARDCODED_LABEL.search('        meta_engine = "ragflow/deepdoc"')
    assert gate.HARDCODED_LABEL.search("meta_engine = 'ragflow/deepdoc'")


def test_detects_route_derived_ocr_flag():
    assert gate.ROUTE_DERIVED_OCR.search("        ocr_used=route == ParseRoute.RAGFLOW_DEEPDOC,")


def test_regression_snippet_would_fail_the_gate():
    hits = [line for line in REGRESSION_SNIPPET.splitlines()
            if gate.HARDCODED_LABEL.search(line) or gate.ROUTE_DERIVED_OCR.search(line)]
    assert len(hits) == 3


def test_current_source_is_clean():
    assert gate.static_scan() == []


def test_legitimate_label_derivation_is_not_flagged():
    """Deriving the label from upstream config must stay allowed."""
    ok = 'engine_label, ocr_capable = _engine_label_for_layout(layout_actual)'
    assert not gate.HARDCODED_LABEL.search(ok)
    assert not gate.ROUTE_DERIVED_OCR.search(ok)
