"""
P2-2：SOP 衝突檢查 + Authority Tier。

稽核文件 §7.5 驗收：
- SOP 與 know-how 衝突時 SOP 優先並顯示差異
- 知識卡包含適用設備、風險、審核者與版本

Authority Tier（權威層級）：
  1. SOP（最高權威）— 正式標準作業程序
  2. Approved Know-how Card — 已審核的老師傅經驗
  3. Draft Know-how Card — 草稿，不可命中
  4. Raw Document — 原始文件

衝突偵測策略：
- 關鍵欄位比對（步驟順序、數值、設備適用範圍）
- 語意相似度（步驟描述的 embedding 相似度）
- 互斥條件（SOP 說 A，know-how 說 B）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuthorityTier(int, Enum):
    """權威層級（數字越大權威越高）。"""
    RAW_DOCUMENT = 1
    DRAFT_KNOWHOW = 2      # 不可命中
    APPROVED_KNOWHOW = 3
    SOP = 4                # 最高權威


@dataclass
class ConflictRecord:
    """衝突記錄。"""
    conflict_type: str  # step_mismatch | value_mismatch | equipment_mismatch | mutual_exclusion
    sop_field: str
    knowhow_field: str
    sop_value: str
    knowhow_value: str
    description: str = ""
    resolved: bool = False
    resolution: str = ""  # sop_wins | knowhow_wins | merged | manual

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "sop_field": self.sop_field,
            "knowhow_field": self.knowhow_field,
            "sop_value": self.sop_value,
            "knowhow_value": self.knowhow_value,
            "description": self.description,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }


class SOPConflictChecker:
    """SOP 衝突檢查器。"""

    def check_conflicts(
        self,
        knowhow_card: Any,  # KnowhowCard
        sop_documents: List[Dict[str, Any]],
    ) -> List[ConflictRecord]:
        """檢查 know-how card 與 SOP 文件的衝突。

        Args:
            knowhow_card: KnowhowCard 物件
            sop_documents: SOP 文件列表，每個含 steps, equipment, cautions 等

        Returns:
            衝突記錄列表
        """
        conflicts: List[ConflictRecord] = []

        for sop in sop_documents:
            sop_steps = sop.get("steps", [])
            sop_equipment = sop.get("applicable_equipment", [])
            sop_cautions = sop.get("cautions", [])
            sop_title = sop.get("title", "")

            # 1. 步驟衝突檢查
            conflicts.extend(self._check_step_mismatches(
                knowhow_card, sop_steps, sop_title
            ))

            # 2. 設備適用範圍衝突
            conflicts.extend(self._check_equipment_mismatches(
                knowhow_card, sop_equipment, sop_title
            ))

            # 3. 注意事項互斥
            conflicts.extend(self._check_caution_conflicts(
                knowhow_card, sop_cautions, sop_title
            ))

        return conflicts

    def _check_step_mismatches(
        self,
        card: Any,
        sop_steps: List[str],
        sop_title: str,
    ) -> List[ConflictRecord]:
        """檢查步驟順序與內容衝突。"""
        conflicts = []
        card_steps = card.steps or []

        # 比對對應步驟的內容差異（無論步驟數量是否相同）
        if card_steps and sop_steps:
            min_len = min(len(card_steps), len(sop_steps))
            for i in range(min_len):
                similarity = self._text_similarity(card_steps[i], sop_steps[i])
                # 相似但不同：0.3 < similarity < 0.95（完全相同 0.95+ 不算衝突）
                if similarity > 0.3 and similarity < 0.95:
                    conflicts.append(ConflictRecord(
                        conflict_type="step_mismatch",
                        sop_field=f"step[{i}]",
                        knowhow_field=f"step[{i}]",
                        sop_value=sop_steps[i][:200],
                        knowhow_value=card_steps[i][:200],
                        description=f"步驟 {i+1} 內容相似但不一致（SOP: {sop_title}）",
                    ))

        return conflicts

    def _check_equipment_mismatches(
        self,
        card: Any,
        sop_equipment: List[str],
        sop_title: str,
    ) -> List[ConflictRecord]:
        """檢查設備適用範圍衝突（雙向）。"""
        conflicts = []
        card_equipment = set(card.applicable_equipment or [])

        if sop_equipment and card_equipment:
            sop_set = set(sop_equipment)
            # 1. know-how 適用但 SOP 不適用（超出範圍）
            extra = card_equipment - sop_set
            if extra and sop_set:
                conflicts.append(ConflictRecord(
                    conflict_type="equipment_mismatch",
                    sop_field="applicable_equipment",
                    knowhow_field="applicable_equipment",
                    sop_value=", ".join(sorted(sop_set)),
                    knowhow_value=", ".join(sorted(extra)),
                    description=f"know-how 適用設備超出 SOP 範圍（SOP: {sop_title}）",
                ))
            # 2. SOP 適用但 know-how 不適用（可能不完整）
            missing = sop_set - card_equipment
            if missing and card_equipment and len(missing) > len(sop_set) * 0.5:
                conflicts.append(ConflictRecord(
                    conflict_type="equipment_mismatch",
                    sop_field="applicable_equipment",
                    knowhow_field="applicable_equipment",
                    sop_value=", ".join(sorted(missing)),
                    knowhow_value=", ".join(sorted(card_equipment)),
                    description=f"know-how 遺漏 SOP 涵蓋的設備（SOP: {sop_title}）",
                ))

        return conflicts

    def _check_caution_conflicts(
        self,
        card: Any,
        sop_cautions: List[str],
        sop_title: str,
    ) -> List[ConflictRecord]:
        """檢查注意事項互斥。"""
        conflicts = []
        card_cautions = card.cautions or []

        # 簡易互斥檢查：若 SOP 說「禁止 X」，know-how 說「可以 X」
        for sop_c in sop_cautions:
            if not sop_c:
                continue
            for card_c in card_cautions:
                if not card_c:
                    continue
                # 檢查互斥關鍵字
                if self._is_mutual_exclusion(sop_c, card_c):
                    conflicts.append(ConflictRecord(
                        conflict_type="mutual_exclusion",
                        sop_field="caution",
                        knowhow_field="caution",
                        sop_value=sop_c[:200],
                        knowhow_value=card_c[:200],
                        description=f"注意事項互斥（SOP: {sop_title}）",
                    ))

        return conflicts

    def _text_similarity(self, text1: str, text2: str) -> float:
        """計算兩段文字的簡易相似度（詞級 Jaccard + 數值差異檢查）。

        改進：字元級 Jaccard 對短文字不準確（「開機」vs「關機」=0.5），
        改用詞級（CJK 逐字 + ASCII 按詞）+ 數值差異加權。
        """
        if not text1 or not text2:
            return 0.0
        # 詞級 tokenize：CJK 逐字，ASCII 按空白分詞
        tokens1 = self._tokenize(text1)
        tokens2 = self._tokenize(text2)
        set1 = set(tokens1)
        set2 = set(tokens2)
        intersection = set1 & set2
        union = set1 | set2
        jaccard = len(intersection) / len(union) if union else 0.0

        # 數值差異檢查：若兩段文字含不同數值，降低相似度
        import re
        nums1 = set(re.findall(r'\d+', text1))
        nums2 = set(re.findall(r'\d+', text2))
        if nums1 and nums2 and nums1 != nums2:
            # 有不同數值，相似度打 8 折
            jaccard *= 0.8

        return jaccard

    def _tokenize(self, text: str) -> List[str]:
        """簡易分詞：CJK 逐字，ASCII 按空白/標點分詞。"""
        import re
        tokens: List[str] = []
        for part in re.split(r'\s+', text):
            # 檢查是否為 ASCII 詞
            if re.match(r'^[a-zA-Z0-9\-]+$', part):
                tokens.append(part.lower())
            else:
                # CJK 逐字
                for c in part:
                    if c.strip():
                        tokens.append(c)
        return tokens

    def _is_mutual_exclusion(self, text1: str, text2: str) -> bool:
        """檢查兩段文字是否互斥。"""
        # 簡易檢查：一方含「禁止/不可/不得」，另一方含「可以/允許/應該」
        prohibit_keywords = ["禁止", "不可", "不得", "嚴禁", "切勿"]
        allow_keywords = ["可以", "允許", "應該", "可", "得"]

        t1_prohibit = any(k in text1 for k in prohibit_keywords)
        t2_allow = any(k in text2 for k in allow_keywords)
        t1_allow = any(k in text1 for k in allow_keywords)
        t2_prohibit = any(k in text2 for k in prohibit_keywords)

        return (t1_prohibit and t2_allow) or (t1_allow and t2_prohibit)


def resolve_conflict_sop_wins(conflict: ConflictRecord) -> ConflictRecord:
    """解決衝突 — SOP 優先。"""
    conflict.resolved = True
    conflict.resolution = "sop_wins"
    return conflict


def resolve_conflict_manual(conflict: ConflictRecord, resolution: str = "") -> ConflictRecord:
    """解決衝突 — 人工裁決。"""
    conflict.resolved = True
    conflict.resolution = resolution or "manual"
    return conflict


# ── 單例 ──

_checker: Optional[SOPConflictChecker] = None


def get_sop_conflict_checker() -> SOPConflictChecker:
    global _checker
    if _checker is None:
        _checker = SOPConflictChecker()
    return _checker