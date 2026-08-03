"""Product-surface honesty for Wiki/Graph (DD-M08 / M09A)."""
from app.api.v1.product_surface import GRAPH_PRODUCT_STATUS, WIKI_PRODUCT_STATUS


def test_wiki_graph_product_status_payloads():
    # Wiki: browse/read UI exists (/knowledge/wiki); admin manual edit creates new
    # revisions; compile stays admin-triggered via API.
    assert WIKI_PRODUCT_STATUS["web_ui"] is True
    assert WIKI_PRODUCT_STATUS["status"] == "beta"
    assert GRAPH_PRODUCT_STATUS["web_ui"] is False
    assert GRAPH_PRODUCT_STATUS["production_write_path"] is False
    assert "api_only" in GRAPH_PRODUCT_STATUS["status"]


def test_orphan_alembic_versions_archived():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    orphan_dir = root / "alembic" / "versions"
    archived = root / "docs" / "archive" / "alembic_versions_orphaned"
    py_left = list(orphan_dir.glob("*.py"))
    assert py_left == [], f"orphan migrations still in alembic/versions: {py_left}"
    assert (archived / "README.md").exists()
    assert len(list(archived.glob("*.py"))) >= 6
