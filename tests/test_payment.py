"""CG-PAY payment API 測試。"""

import pytest





@pytest.mark.asyncio

async def test_checkout_requires_merchant_config(client, superuser_headers):

    """未設定 NewebPay 時 checkout 回 503。"""

    r = await client.post(

        "/api/v1/payment/checkout",

        headers=superuser_headers,

        json={"target_plan": "team"},

    )

    assert r.status_code == 503





@pytest.mark.asyncio

async def test_list_payment_plans(client):

    r = await client.get("/api/v1/payment/plans")

    assert r.status_code == 200

    plans = {p["plan"] for p in r.json()}

    assert "team" in plans

    assert "business" in plans

