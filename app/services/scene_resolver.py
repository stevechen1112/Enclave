"""
MKA Scene Resolver — QR/條碼場景解析。

對照 ENGINEERING_PLAN.md §4.4、§5.3：
- SceneContext 必須是受驗證的結構，不是任意 prompt
- QR 只攜帶 opaque identifier；實際場景資料由後端解析
- 禁止直接把掃描字串拼入 prompt
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class SceneContext:
    """受驗證的場景上下文（§4.4）。"""
    site_id: str = ""
    plant_id: str = ""
    line_id: str = ""
    equipment_id: str = ""
    equipment_model: str = ""
    work_order_id: str = ""
    product_id: str = ""
    part_number: str = ""
    customer_id: str = ""
    document_version_scope: str = ""
    resolved_from: str = "user"  # qr | barcode | user | system
    resolved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # 用於檢索的 metadata filter
    @property
    def retrieval_filter(self) -> Dict[str, Any]:
        """產生可用於 kb_retrieval filter_dict 的 metadata 過濾條件。"""
        filt: Dict[str, Any] = {}
        if self.equipment_id:
            filt["equipment_id"] = self.equipment_id
        if self.part_number:
            filt["part_number"] = self.part_number
        if self.product_id:
            filt["product_id"] = self.product_id
        if self.work_order_id:
            filt["work_order_id"] = self.work_order_id
        return filt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "site_id": self.site_id,
            "plant_id": self.plant_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "equipment_model": self.equipment_model,
            "work_order_id": self.work_order_id,
            "product_id": self.product_id,
            "part_number": self.part_number,
            "customer_id": self.customer_id,
            "document_version_scope": self.document_version_scope,
            "resolved_from": self.resolved_from,
            "resolved_at": self.resolved_at,
        }


class SceneResolver:
    """場景解析器 — 從 QR token / barcode 解析 SceneContext。

    安全設計（§5.3、§12.2）：
    - QR 只攜帶 opaque identifier，不直接包含場景資料
    - 實際場景資料由後端 DB 查詢解析
    - 禁止直接把掃描字串拼入 prompt
    - 所有外部輸入視為 untrusted
    """

    def __init__(self, db: Optional[Any] = None, tenant_id: Optional[Any] = None):
        self.db = db
        self.tenant_id = tenant_id

    def resolve(self, qr_token: str = "", barcode: str = "") -> Optional[SceneContext]:
        """解析 QR token 或 barcode 為 SceneContext。

        Args:
            qr_token: QR Code 掃描結果（opaque identifier）
            barcode: 條碼掃描結果

        Returns:
            SceneContext 或 None（解析失敗）
        """
        if not qr_token and not barcode:
            return None

        # QR token 解析（opaque identifier → DB 查詢）
        if qr_token:
            return self._resolve_qr(qr_token)

        # Barcode 解析
        if barcode:
            return self._resolve_barcode(barcode)

        return None

    def _resolve_qr(self, token: str) -> Optional[SceneContext]:
        """從 QR token 解析場景。

        QR token 格式（首版）：
        - eq:{equipment_id} — 設備 QR
        - wo:{work_order_id} — 工單 QR
        - prod:{product_id} — 產品 QR
        - {uuid} — opaque ID，需 DB 查詢
        """
        token = token.strip()

        # 安全檢查：防止 prompt injection
        if any(c in token for c in ["\n", "\r", ";", "'", '"', "<", ">"]):
            logger.warning(f"QR token contains suspicious characters: {token[:50]}")
            return None

        # 格式化 token
        if token.startswith("eq:"):
            equipment_id = token[3:]
            return SceneContext(
                equipment_id=equipment_id,
                resolved_from="qr",
            )
        elif token.startswith("wo:"):
            work_order_id = token[3:]
            return SceneContext(
                work_order_id=work_order_id,
                resolved_from="qr",
            )
        elif token.startswith("prod:"):
            product_id = token[5:]
            return SceneContext(
                product_id=product_id,
                resolved_from="qr",
            )
        else:
            # Opaque ID — DB lookup via SceneRegistry
            if self.db is not None:
                return self._resolve_opaque_db(token)
            logger.info(f"QR opaque token: {token[:20]}... (DB lookup not yet implemented)")
            return SceneContext(
                resolved_from="qr",
                document_version_scope=f"opaque:{token[:50]}",
            )

    def _resolve_opaque_db(self, token: str) -> Optional[SceneContext]:
        """Resolve opaque QR token via SceneRegistry DB lookup."""
        from app.models.mka import SceneRegistry

        query = self.db.query(SceneRegistry).filter(
            SceneRegistry.token == token,
            SceneRegistry.active.is_(True),
        )
        if self.tenant_id is not None:
            query = query.filter(SceneRegistry.tenant_id == self.tenant_id)
        row = query.first()
        if row is None:
            logger.warning(f"QR opaque token not found in registry: {token[:20]}...")
            return None

        return SceneContext(
            site_id=row.site_id or "",
            plant_id=row.plant_id or "",
            line_id=row.line_id or "",
            equipment_id=row.equipment_id or "",
            equipment_model=row.equipment_model or "",
            work_order_id=row.work_order_id or "",
            product_id=row.product_id or "",
            part_number=row.part_number or "",
            customer_id=row.customer_id or "",
            document_version_scope=row.document_version_scope or "",
            resolved_from="qr",
        )

    def _resolve_barcode(self, code: str) -> Optional[SceneContext]:
        """從條碼解析場景。

        條碼格式（首版）：
        - 純數字 → part_number
        - PN:{part_number} — 明確料號
        """
        code = code.strip()

        # 安全檢查
        if any(c in code for c in ["\n", "\r", ";", "'", '"', "<", ">"]):
            logger.warning(f"Barcode contains suspicious characters: {code[:50]}")
            return None

        if code.startswith("PN:"):
            return SceneContext(
                part_number=code[3:],
                resolved_from="barcode",
            )
        elif code.isdigit():
            return SceneContext(
                part_number=code,
                resolved_from="barcode",
            )
        else:
            return SceneContext(
                part_number=code,
                resolved_from="barcode",
            )


# ── 單例 ──

_resolver: Optional[SceneResolver] = None


def get_scene_resolver() -> SceneResolver:
    global _resolver
    if _resolver is None:
        _resolver = SceneResolver()
    return _resolver