"""B4: DeepDOC `positions` -> page/bbox lineage extraction."""
from app.gateway.adapters.ragflow_http import RAGFlowHTTPAdapter


def test_positions_derive_page_and_bbox():
    c = {"content": "hello", "positions": [[1, 168, 444, 87, 104], [3, 146, 451, 226, 250]]}
    out = RAGFlowHTTPAdapter._chunk_payload(c)
    assert out["page"] == 1
    assert out["bbox"] == {"x": 168.0, "y": 87.0, "w": 276.0, "h": 17.0}


def test_explicit_page_num_and_bbox_win():
    c = {"content": "x", "page_num": 7, "bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
         "positions": [[1, 168, 444, 87, 104]]}
    out = RAGFlowHTTPAdapter._chunk_payload(c)
    assert out["page"] == 7
    assert out["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}


def test_no_positions_no_coords():
    c = {"content": "x"}
    out = RAGFlowHTTPAdapter._chunk_payload(c)
    assert out["page"] is None
    assert out["bbox"] is None


def test_malformed_positions_safe():
    c = {"content": "x", "positions": [["bad"], None, []]}
    out = RAGFlowHTTPAdapter._chunk_payload(c)
    assert out["page"] is None or isinstance(out["page"], int)
