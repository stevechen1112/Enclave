"""Legacy HR deterministic answer compatibility boundary.

Owner: Knowledge/RAG backend. Retirement condition: the generic structured
record resolver reaches parity on the frozen HR regression set. This module may
not be imported by generic retrieval or evidence services.
"""
from app.services.structured_answers import try_structured_answer
from datetime import date

PACK_ID = "hr-compatibility"
PACK_VERSION = "1.0"


def resolve(tenant_id, question, history=None):
    return try_structured_answer(tenant_id, question, history=history)


def calculation_guidance(question: str) -> list[str]:
    """Legacy HR calculation hints, isolated from the generic orchestrator."""
    today = date.today()
    today_str = f"{today.year}年{today.month}月{today.day}日"
    hints: list[str] = []
    if "特休" in question or "特別休假" in question:
        hints.extend(["特休天數依勞基法第38條，按實際到職日計算年資。",
                      "年資區間：未滿6個月=0天，6個月至未滿1年=3天，1年=7天，2年=10天，3年=14天，5年=15天，10年以上每年加1天、最多30天。",
                      f"若問題含到職日，計算到今天（{today_str}）後再查對照表。"])
    if "資遣費" in question:
        hints.append("資遣費公式：年資（年）×0.5×月平均工資；不可把月薪除以30。")
    if "加班" in question:
        hints.extend(["時薪=月薪/30/8。", "平日前2小時1.34倍，第3小時起1.67倍；必須分段計算。",
                      "休息日前2小時1.34倍，第3至8小時1.67倍，第9小時起2.67倍。"])
    if "勞保" in question:
        hints.append("薪資條若列出勞保自付額，直接引用該筆同列數值。")
    if "離職" in question and "資遣費" in question:
        hints.append("自請離職不適用資遣費；需先確認終止契約原因。")
    return hints
