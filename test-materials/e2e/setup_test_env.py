"""MKA UX 測試環境建置（一次性）。

做的事：
1. DB：建立 5 個測試帳號（sales/field/master/newcomer/viewer）於 Demo Tenant
2. API：seed 職能與模組 → 指派職能 → 建立 EQ-100 場景 → 上傳並啟用 T01–T03 版型

用法：cd Enclave && python test-materials/e2e/setup_test_env.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# 容器內無 .env（由 env_file 注入），僅在本機開發時載入
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BASE = os.getenv("E2E_API_BASE", "http://127.0.0.1:8005/api/v1")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
TM = ROOT / "test-materials"
PASSWORD = "Demo12345"

USERS = [
    ("sales@demo.mka", "employee", "業務測試 王小明"),
    ("field@demo.mka", "employee", "現場測試 李阿明"),
    ("master@demo.mka", "employee", "師傅測試 林火旺"),
    ("newcomer@demo.mka", "employee", "新人測試 陳小弟"),
    ("viewer@demo.mka", "viewer", "唯讀測試"),
]

ROLE_ASSIGN = {
    "sales@demo.mka": "sales",
    "field@demo.mka": "equipment",
    "master@demo.mka": "supervisor",
    "newcomer@demo.mka": "newcomer",
}


def ensure_users() -> dict:
    """DB 層建立帳號，回傳 email→user_id。"""
    from app.core.security import get_password_hash
    from app.db.session import SessionLocal
    from app.models.tenant import Tenant
    from app.models.user import User

    db = SessionLocal()
    ids: dict = {}
    try:
        tenant = db.query(Tenant).filter(Tenant.name == "Demo Tenant").first()
        if not tenant:
            raise SystemExit("Demo Tenant missing — run scripts/initial_data.py first")
        for email, role, name in USERS:
            u = db.query(User).filter(User.email == email).first()
            if u is None:
                u = User(
                    id=uuid4(), email=email, full_name=name, role=role,
                    hashed_password=get_password_hash(PASSWORD),
                    tenant_id=tenant.id, status="active",
                )
                db.add(u)
                print(f"created user {email} role={role}")
            else:
                u.role = role
                u.hashed_password = get_password_hash(PASSWORD)
                u.full_name = name
                u.tenant_id = tenant.id
                u.status = "active"
                print(f"updated user {email} role={role}")
            db.flush()
            ids[email] = str(u.id)
        db.commit()
    finally:
        db.close()
    return ids


def login(client: httpx.Client, email: str, password: str) -> dict:
    r = client.post("/auth/login/access-token", data={"username": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    user_ids = ensure_users()

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        admin = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

        # 1. seed 職能與模組
        r = client.post("/job-roles/seed", headers=admin)
        print("seed:", r.status_code, r.text[:200])

        # 2. 指派職能
        roles = client.get("/job-roles", headers=admin).json()
        role_list = roles if isinstance(roles, list) else roles.get("items", roles.get("roles", []))
        by_key = {r.get("role_key"): r.get("id") for r in role_list}
        print("available job roles:", list(by_key))
        for email, role_key in ROLE_ASSIGN.items():
            rid = by_key.get(role_key)
            if not rid:
                print(f"!! role_key {role_key} not found, skip {email}")
                continue
            r = client.post("/job-roles/assignments", headers=admin, json={
                "user_id": user_ids[email], "job_role_id": rid, "is_primary": True,
            })
            print(f"assign {email} -> {role_key}: {r.status_code} {r.text[:120]}")

        # 3. 建立 EQ-100 場景
        r = client.post("/scene/registry", headers=admin, json={
            "token": "EQ100-DEMO-QR-001",
            "label": "EQ-100 高速捲繞機（二廠 A 產線）",
            "plant_id": "二廠",
            "line_id": "A 產線",
            "equipment_id": "EQ-100-01",
            "equipment_model": "EQ-100",
            "product_id": "P-200",
            "active": True,
        })
        print("scene registry:", r.status_code, r.text[:200])

        # 4. 上傳並啟用版型 T01–T03
        templates = [
            ("quote", "T01_報價單版型.docx"),
            ("incident_report", "T02_異常報告版型.xlsx"),
            ("shift_handover", "T03_交接班紀錄版型.xlsx"),
        ]
        for form_key, fname in templates:
            fpath = TM / "templates" / fname
            with open(fpath, "rb") as f:
                r = client.post(
                    "/forms/templates", headers=admin,
                    data={"form_key": form_key, "name": fname, "version": "1.0"},
                    files={"file": (fname, f)},
                )
            print(f"template upload {form_key}: {r.status_code} {r.text[:200]}")
            if r.status_code in (200, 201):
                body = r.json()
                tid = body.get("id") or body.get("template_id")
                if tid:
                    ra = client.post(f"/forms/templates/{tid}/activate", headers=admin)
                    print(f"  activate {tid}: {ra.status_code} {ra.text[:120]}")

    print("\n=== setup done ===")
    print(json.dumps({"user_ids": user_ids, "password": PASSWORD}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
