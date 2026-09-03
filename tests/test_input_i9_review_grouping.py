from app.services.review_workspace import group_review_items


def _item(item_id, asset_id, *, risk="low", confidence=0.9, blocked=None):
    return {
        "id": item_id,
        "source_group_key": f"asset:{asset_id}",
        "source_asset_id": asset_id,
        "title": f"來源 {asset_id}",
        "asset_kind": "video",
        "risk_level": risk,
        "confidence": confidence,
        "blocked_reasons": blocked or [],
    }


def test_review_items_group_by_source_instead_of_candidate_count():
    items = [
        *[_item(f"a-{index}", "a", risk="high" if index == 0 else "low") for index in range(49)],
        *[_item(f"b-{index}", "b", confidence=0.7 if index < 3 else 0.9) for index in range(28)],
    ]

    groups = group_review_items(items)

    assert len(groups) == 2
    assert groups[0]["item_count"] == 49
    assert groups[0]["high_risk_count"] == 1
    assert groups[1]["item_count"] == 28
    assert groups[1]["low_confidence_count"] == 3


def test_provider_without_source_identity_fails_safe_to_one_item_group():
    rows = [
        {"id": "one", "title": "同名", "asset_kind": "record", "risk_level": "low", "confidence": None, "blocked_reasons": []},
        {"id": "two", "title": "同名", "asset_kind": "record", "risk_level": "low", "confidence": None, "blocked_reasons": []},
    ]

    groups = group_review_items(rows)

    assert [group["key"] for group in groups] == ["item:one", "item:two"]
