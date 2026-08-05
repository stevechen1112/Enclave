"""可售方案目錄（CG-PAY）— 配額對齊 PLAN_QUOTAS，價格為起始建議。"""

from app.schemas.tenant import PLAN_QUOTAS

# 自助升級路徑：pilot → team → business（enterprise 合約制，不走 MPG）
PLAN_CATALOG = {
    "pilot": {
        "display_name": "Pilot",
        "price_monthly_twd": 0,
        "order": 0,
        "self_checkout": False,
    },
    "team": {
        "display_name": "Team",
        "price_monthly_twd": 2990,
        "order": 1,
        "self_checkout": True,
    },
    "business": {
        "display_name": "Business",
        "price_monthly_twd": 9900,
        "order": 2,
        "self_checkout": True,
    },
    "enterprise": {
        "display_name": "Enterprise",
        "price_monthly_twd": None,
        "order": 3,
        "self_checkout": False,
    },
    # 遺留方案名（相容）
    "free": {"display_name": "Free", "price_monthly_twd": 0, "order": 0, "self_checkout": False},
    "pro": {"display_name": "Pro", "price_monthly_twd": 1990, "order": 1, "self_checkout": True},
}


def get_plan(plan_name: str) -> dict:
    base = PLAN_CATALOG.get(plan_name)
    if not base:
        raise KeyError(plan_name)
    out = dict(base)
    out["quotas"] = PLAN_QUOTAS.get(plan_name, {})
    return out


def list_checkout_plans() -> list[str]:
    return [k for k, v in PLAN_CATALOG.items() if v.get("self_checkout")]
