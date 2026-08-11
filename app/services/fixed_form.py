"""
P1-2：Fixed Form Schema — 結構化表單。

稽核文件 §11.3 完成定義：
- schema
- required fields
- deterministic calculations
- provenance
- preview
- version
- approval
- formal export

完成不等於 LLM 生成 Markdown，而是有 schema 驗證、必填檢查、
確定性計算、來源溯源、版本控制、簽核狀態機與正式匯出。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class FieldType(str, Enum):
    """表單欄位類型。"""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    BOOLEAN = "boolean"
    AMOUNT = "amount"  # 金額（含貨幣）
    PART_NUMBER = "part_number"  # 料號
    TABLE = "table"  # 表格（多列多欄）


class FormStatus(str, Enum):
    """表單狀態機。"""
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"  # 被新版本取代


@dataclass
class FormField:
    """表單欄位定義。"""
    name: str
    label: str
    type: FieldType
    required: bool = True
    default: Any = None
    options: List[str] = field(default_factory=list)  # for select/multi_select
    min_value: Optional[float] = None  # for number/amount
    max_value: Optional[float] = None
    precision: int = 2  # for amount — 小數位數
    currency: str = "TWD"  # for amount
    description: str = ""
    provenance: str = ""  # 來源（哪個 chunk 或文件）
    calculated: bool = False  # 是否為計算欄位
    formula: str = ""  # 計算公式（若 calculated=True）


@dataclass
class FixedFormSchema:
    """固定表單 Schema 定義。"""
    name: str
    version: str = "1.0"
    description: str = ""
    fields: List[FormField] = field(default_factory=list)
    require_approval: bool = True
    approver_roles: List[str] = field(default_factory=list)  # 簽核角色

    def get_field(self, name: str) -> Optional[FormField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_required_fields(self) -> List[FormField]:
        return [f for f in self.fields if f.required]


@dataclass
class FixedFormInstance:
    """表單實例（填寫後的表單）。"""
    schema_name: str
    schema_version: str
    values: Dict[str, Any] = field(default_factory=dict)
    status: FormStatus = FormStatus.DRAFT
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    approved_by: str = ""
    approved_at: str = ""
    rejection_reason: str = ""
    provenance: Dict[str, str] = field(default_factory=dict)  # field_name → source quote

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "values": self.values,
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "rejection_reason": self.rejection_reason,
            "provenance": self.provenance,
        }


class FixedFormValidator:
    """表單驗證器。"""

    @staticmethod
    def validate(schema: FixedFormSchema, values: Dict[str, Any]) -> List[str]:
        """驗證表單值，回傳錯誤訊息列表（空 = 通過）。

        檢查：
        1. 必填欄位
        2. 類型正確
        3. 數值範圍
        4. select 選項合法
        5. 計算欄位正確
        """
        errors: List[str] = []

        # 1. 必填檢查
        for f in schema.get_required_fields():
            if f.name not in values or values[f.name] is None or values[f.name] == "":
                errors.append(f"必填欄位缺失: {f.label} ({f.name})")

        # 2. 類型與範圍檢查
        for f in schema.fields:
            if f.name not in values:
                continue
            val = values[f.name]

            if f.type == FieldType.NUMBER:
                if not isinstance(val, (int, float)):
                    errors.append(f"{f.label} 必須是數字，實際: {type(val).__name__}")
                elif f.min_value is not None and val < f.min_value:
                    errors.append(f"{f.label} 不得小於 {f.min_value}")
                elif f.max_value is not None and val > f.max_value:
                    errors.append(f"{f.label} 不得大於 {f.max_value}")

            elif f.type == FieldType.AMOUNT:
                if not isinstance(val, (int, float)):
                    errors.append(f"{f.label} 必須是金額數字，實際: {type(val).__name__}")
                elif f.precision > 0:
                    # 檢查小數位數
                    rounded = round(val, f.precision)
                    if rounded != val:
                        errors.append(f"{f.label} 小數位數不得超過 {f.precision} 位")

            elif f.type == FieldType.SELECT:
                if val not in f.options:
                    errors.append(f"{f.label} 選項不合法: {val}，可選: {f.options}")

            elif f.type == FieldType.MULTI_SELECT:
                if not isinstance(val, list):
                    errors.append(f"{f.label} 必須是多選列表")
                else:
                    for v in val:
                        if v not in f.options:
                            errors.append(f"{f.label} 選項不合法: {v}")

            elif f.type == FieldType.BOOLEAN:
                if not isinstance(val, bool):
                    errors.append(f"{f.label} 必須是布林值")

        # 3. 計算欄位檢查
        for f in schema.fields:
            if f.calculated and f.name in values:
                expected = FixedFormCalculator.calculate(f, values)
                if expected is not None and abs(float(values[f.name]) - expected) > 0.01:
                    errors.append(
                        f"{f.label} 計算不正確: 預期 {expected}，實際 {values[f.name]}"
                    )

        return errors


class FixedFormCalculator:
    """確定性計算引擎。"""

    @staticmethod
    def calculate(field: FormField, values: Dict[str, Any]) -> Optional[float]:
        """根據公式計算欄位值。

        支援的公式語法（簡易）：
        - SUM(field1, field2, ...) — 加總
        - SUBTOTAL(field1, field2) — 小計
        - TAX(subtotal, rate) — 稅額
        - TOTAL(subtotal, tax) — 含稅總計
        - MULTIPLY(field1, field2) — 乘法
        """
        formula = field.formula
        if not formula:
            return None

        try:
            # 解析公式
            if formula.startswith("SUM("):
                args = formula[4:-1].split(",")
                args = [a.strip() for a in args]
                return sum(float(values.get(a, 0)) for a in args)

            elif formula.startswith("MULTIPLY("):
                args = formula[9:-1].split(",")
                args = [a.strip() for a in args]
                result = 1.0
                for a in args:
                    result *= float(values.get(a, 0))
                return result

            elif formula.startswith("TAX("):
                args = formula[4:-1].split(",")
                subtotal = float(values.get(args[0].strip(), 0))
                rate_token = args[1].strip()
                rate_value = values.get(rate_token, rate_token.rstrip("%"))
                rate = float(rate_value) / 100
                return round(subtotal * rate, 2)

            elif formula.startswith("TOTAL("):
                args = formula[6:-1].split(",")
                subtotal = float(values.get(args[0].strip(), 0))
                tax = float(values.get(args[1].strip(), 0))
                return round(subtotal + tax, 2)

            else:
                logger.warning(f"Unknown formula: {formula}")
                return None

        except (ValueError, KeyError, IndexError) as exc:
            logger.warning(f"Formula calculation failed: {formula} — {exc}")
            return None


class FixedFormRegistry:
    """表單 Schema 註冊表。"""

    def __init__(self):
        self._schemas: Dict[str, FixedFormSchema] = {}

    def register(self, schema: FixedFormSchema) -> None:
        self._schemas[schema.name] = schema
        logger.info(f"Registered fixed form schema: {schema.name} v{schema.version}")

    def get(self, name: str) -> Optional[FixedFormSchema]:
        return self._schemas.get(name)

    def list_forms(self) -> List[str]:
        return sorted(self._schemas.keys())


# ── 預設表單 Schema（製造業常見）──

def _create_default_schemas() -> Dict[str, FixedFormSchema]:
    """建立製造業常見表單 Schema。"""
    schemas: Dict[str, FixedFormSchema] = {}

    # 報價單
    quote_form = FixedFormSchema(
        name="quote",
        version="1.0",
        description="報價單",
        require_approval=True,
        approver_roles=["owner", "finance"],
        fields=[
            FormField(name="customer", label="客戶名稱", type=FieldType.TEXT, required=True),
            FormField(name="part_number", label="料號", type=FieldType.PART_NUMBER, required=True),
            FormField(name="quantity", label="數量", type=FieldType.NUMBER, required=True, min_value=1),
            FormField(name="unit_price", label="單價", type=FieldType.AMOUNT, required=True, min_value=0),
            FormField(name="subtotal", label="小計", type=FieldType.AMOUNT, calculated=True,
                      formula="MULTIPLY(quantity, unit_price)"),
            FormField(name="tax_rate", label="稅率", type=FieldType.NUMBER, default=5, min_value=0, max_value=100),
            FormField(name="tax", label="稅額", type=FieldType.AMOUNT, calculated=True,
                      formula="TAX(subtotal, tax_rate)"),
            FormField(name="total", label="含稅總計", type=FieldType.AMOUNT, calculated=True,
                      formula="TOTAL(subtotal, tax)"),
            FormField(name="valid_until", label="報價有效期限", type=FieldType.DATE, required=True),
            FormField(name="payment_terms", label="付款條件", type=FieldType.SELECT,
                      options=["現金", "月結30天", "月結60天", "預付"], required=True),
        ],
    )
    schemas["quote"] = quote_form

    # 採購單
    po_form = FixedFormSchema(
        name="purchase_order",
        version="1.0",
        description="採購單",
        require_approval=True,
        approver_roles=["owner", "finance"],
        fields=[
            FormField(name="supplier", label="供應商", type=FieldType.TEXT, required=True),
            FormField(name="part_number", label="料號", type=FieldType.PART_NUMBER, required=True),
            FormField(name="quantity", label="採購數量", type=FieldType.NUMBER, required=True, min_value=1),
            FormField(name="unit_price", label="單價", type=FieldType.AMOUNT, required=True, min_value=0),
            FormField(name="subtotal", label="小計", type=FieldType.AMOUNT, calculated=True,
                      formula="MULTIPLY(quantity, unit_price)"),
            FormField(name="tax", label="稅額", type=FieldType.AMOUNT, calculated=True,
                      formula="TAX(subtotal, 5)"),
            FormField(name="total", label="含稅總計", type=FieldType.AMOUNT, calculated=True,
                      formula="TOTAL(subtotal, tax)"),
            FormField(name="expected_date", label="預計交貨日", type=FieldType.DATE, required=True),
        ],
    )
    schemas["purchase_order"] = po_form

    # 現場異常回報（MKA-P3 模組 C 產品切片）
    incident_form = FixedFormSchema(
        name="incident_report",
        version="1.0",
        description="現場異常回報單",
        require_approval=True,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="equipment_id", label="設備編號", type=FieldType.TEXT, required=True),
            FormField(name="location", label="發生位置／產線", type=FieldType.TEXT, required=True),
            FormField(name="occurred_at", label="發生時間", type=FieldType.DATE, required=True),
            FormField(name="category", label="異常類別", type=FieldType.SELECT,
                      options=["設備故障", "品質異常", "安全事件", "停機", "其他"], required=True),
            FormField(name="severity", label="嚴重程度", type=FieldType.SELECT,
                      options=["輕微（可繼續生產）", "中等（需注意）", "嚴重（已停機）"], required=True),
            FormField(name="description", label="異常狀況描述", type=FieldType.TEXT, required=True),
            FormField(name="immediate_action", label="已採取的緊急處置", type=FieldType.TEXT, required=False),
            FormField(name="reporter", label="回報人", type=FieldType.TEXT, required=True),
        ],
    )
    schemas["incident_report"] = incident_form

    # 交接班紀錄（MKA-P3 模組 C）
    handover_form = FixedFormSchema(
        name="shift_handover",
        version="1.0",
        description="交接班紀錄",
        require_approval=True,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="shift_date", label="班次日期", type=FieldType.DATE, required=True),
            FormField(name="shift", label="班次", type=FieldType.SELECT,
                      options=["早班", "中班", "晚班"], required=True),
            FormField(name="line", label="產線／區域", type=FieldType.TEXT, required=True),
            FormField(name="outgoing", label="交班人", type=FieldType.TEXT, required=True),
            FormField(name="incoming", label="接班人", type=FieldType.TEXT, required=True),
            FormField(name="production_summary", label="本班生產狀況", type=FieldType.TEXT, required=True),
            FormField(name="pending_issues", label="未完成事項／待追蹤", type=FieldType.TEXT, required=False),
            FormField(name="equipment_notes", label="設備注意事項", type=FieldType.TEXT, required=False),
        ],
    )
    schemas["shift_handover"] = handover_form

    # 會議／拜訪紀錄
    schemas["meeting_visit"] = FixedFormSchema(
        name="meeting_visit",
        version="1.0",
        description="會議／拜訪紀錄",
        require_approval=False,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="customer_id", label="客戶", type=FieldType.TEXT, required=True),
            FormField(name="visit_date", label="日期", type=FieldType.DATE, required=True),
            FormField(name="attendees", label="與會者", type=FieldType.TEXT, required=True),
            FormField(name="purpose", label="目的", type=FieldType.TEXT, required=True),
            FormField(name="summary", label="摘要", type=FieldType.TEXT, required=True),
            FormField(name="next_actions", label="後續行動", type=FieldType.TEXT, required=False),
        ],
    )

    # 設備維修
    schemas["equipment_repair"] = FixedFormSchema(
        name="equipment_repair",
        version="1.0",
        description="設備維修紀錄",
        require_approval=True,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="equipment_id", label="設備編號", type=FieldType.TEXT, required=True),
            FormField(name="equipment_model", label="機型", type=FieldType.TEXT, required=False),
            FormField(name="fault_symptom", label="故障現象", type=FieldType.TEXT, required=True),
            FormField(name="root_cause", label="原因分析", type=FieldType.TEXT, required=False),
            FormField(name="repair_action", label="維修處置", type=FieldType.TEXT, required=True),
            FormField(name="parts_used", label="更換零件", type=FieldType.TEXT, required=False),
            FormField(name="technician", label="維修人員", type=FieldType.TEXT, required=True),
            FormField(name="completed_at", label="完成日", type=FieldType.DATE, required=True),
        ],
    )

    # 請款單
    schemas["payment_request"] = FixedFormSchema(
        name="payment_request",
        version="1.0",
        description="請款單",
        require_approval=True,
        approver_roles=["owner", "finance"],
        fields=[
            FormField(name="customer", label="客戶", type=FieldType.TEXT, required=True),
            FormField(name="invoice_no", label="發票／對帳單號", type=FieldType.TEXT, required=True),
            FormField(name="amount", label="請款金額", type=FieldType.AMOUNT, required=True, min_value=0),
            FormField(name="due_date", label="收款期限", type=FieldType.DATE, required=True),
            FormField(name="description", label="說明", type=FieldType.TEXT, required=False),
        ],
    )

    # 8D／CAPA
    schemas["quality_8d"] = FixedFormSchema(
        name="quality_8d",
        version="1.0",
        description="8D／CAPA",
        require_approval=True,
        approver_roles=["owner", "admin", "quality"],
        fields=[
            FormField(name="customer_id", label="客戶／客訴來源", type=FieldType.TEXT, required=True),
            FormField(name="part_number", label="料號", type=FieldType.PART_NUMBER, required=True),
            FormField(name="problem", label="問題描述", type=FieldType.TEXT, required=True),
            FormField(name="containment", label="圍堵措施（D3）", type=FieldType.TEXT, required=True),
            FormField(name="root_cause", label="根因（D4）", type=FieldType.TEXT, required=True),
            FormField(name="corrective_action", label="矯正措施（D5）", type=FieldType.TEXT, required=True),
            FormField(name="owner", label="責任人", type=FieldType.TEXT, required=True),
            FormField(name="due_date", label="完成期限", type=FieldType.DATE, required=True),
        ],
    )
    schemas["capa"] = FixedFormSchema(
        name="capa",
        version="1.0",
        description="CAPA 追蹤",
        require_approval=True,
        approver_roles=["owner", "admin", "quality"],
        fields=[
            FormField(name="related_8d", label="關聯 8D 編號", type=FieldType.TEXT, required=False),
            FormField(name="action", label="改善行動", type=FieldType.TEXT, required=True),
            FormField(name="owner", label="責任人", type=FieldType.TEXT, required=True),
            FormField(name="due_date", label="期限", type=FieldType.DATE, required=True),
            FormField(name="status_note", label="進度說明", type=FieldType.TEXT, required=False),
            FormField(name="effectiveness", label="有效性驗證", type=FieldType.TEXT, required=False),
        ],
    )

    # 新人訓練 checklist
    schemas["training_checklist"] = FixedFormSchema(
        name="training_checklist",
        version="1.0",
        description="新人訓練 Checklist",
        require_approval=True,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="trainee", label="受訓人", type=FieldType.TEXT, required=True),
            FormField(name="job_role", label="職務", type=FieldType.TEXT, required=True),
            FormField(name="required_docs", label="必讀文件", type=FieldType.TEXT, required=True),
            FormField(name="quiz_score", label="情境測驗分數", type=FieldType.NUMBER, required=False, min_value=0, max_value=100),
            FormField(name="common_mistakes", label="常見錯誤複習", type=FieldType.TEXT, required=False),
            FormField(name="mentor", label="指導人", type=FieldType.TEXT, required=True),
            FormField(name="completed_at", label="完成日", type=FieldType.DATE, required=False),
        ],
    )

    # 工作日報（職能任務平台 Phase 6：現場職能）
    schemas["daily_report"] = FixedFormSchema(
        name="daily_report",
        version="1.0",
        description="工作日報",
        require_approval=False,
        approver_roles=["owner", "admin"],
        fields=[
            FormField(name="report_date", label="日期", type=FieldType.DATE, required=True),
            FormField(name="shift", label="班次", type=FieldType.SELECT,
                      options=["早班", "中班", "晚班", "常日班"], required=True),
            FormField(name="line", label="產線／區域", type=FieldType.TEXT, required=True),
            FormField(name="work_summary", label="今日工作內容", type=FieldType.TEXT, required=True),
            FormField(name="issues", label="異常／待追蹤", type=FieldType.TEXT, required=False),
            FormField(name="tomorrow_plan", label="明日計畫", type=FieldType.TEXT, required=False),
        ],
    )

    return schemas


# ── 單例 ──

_registry: Optional[FixedFormRegistry] = None


def get_form_registry() -> FixedFormRegistry:
    global _registry
    if _registry is None:
        _registry = FixedFormRegistry()
        for name, schema in _create_default_schemas().items():
            _registry.register(schema)
    return _registry