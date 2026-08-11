"""SceneContext → retrieval filter / form prefill helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional


_SCENE_FILTER_KEYS = (
    "equipment_id",
    "equipment_model",
    "part_number",
    "product_id",
    "work_order_id",
    "customer_id",
    "site_id",
    "plant_id",
    "line_id",
    "document_version_scope",
)


def scene_to_filter_dict(scene: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build metadata filter from SceneContext (only non-empty keys)."""
    if not scene:
        return {}
    out: Dict[str, Any] = {}
    for key in _SCENE_FILTER_KEYS:
        value = scene.get(key)
        if value is None or value == "":
            continue
        out[key] = str(value)
    return out


def scene_question_hint(scene: Optional[Dict[str, Any]]) -> str:
    """Soft constraint appended to question when hard metadata filter is empty-ish."""
    filt = scene_to_filter_dict(scene)
    if not filt:
        return ""
    parts = [f"{k}={v}" for k, v in filt.items()]
    return "［場景限定：" + "；".join(parts) + "］"
