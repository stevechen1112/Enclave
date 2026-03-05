"""
Documents Tests — /api/v1/documents
測試文件上傳、列表、查詢、刪除，以及角色限制
不使用任何 mock — Celery 任務非同步執行，測試只驗證 API 回應
"""
import pytest
from httpx import AsyncClient
from tests.conftest import create_tenant, create_user, login_user

TXT_CONTENT = b"This is a test document for Enclave integration tests."
CSV_CONTENT = b"\xe5\xa7\x93\xe5\x90\x8d,\xe9\x83\xa8\xe9\x96\x80\n\xe7\x8e\x8b\xe5\xb0\x8f\xe6\x98\x8e,\xe5\xb7\xa5\xe7\xa8\x8b\xe9\x83\xa8\n"


@pytest.mark.asyncio
async def test_hr_can_upload_document(client: AsyncClient, superuser_headers: dict):
    """HR 可以上傳文件，回應包含文件 id 與 pending/upload 狀態"""
    t = await create_tenant(client, superuser_headers, {"name": "DocCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@docco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@docco.com", "HR123!")

    resp = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("policy.txt", TXT_CONTENT, "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["filename"] == "policy.txt"
    assert data["status"] in ("pending", "upload", "uploading", "parsing", "processing", "completed")


@pytest.mark.asyncio
async def test_uploaded_document_appears_in_list(client: AsyncClient, superuser_headers: dict):
    """上傳後文件應出現在列表中"""
    t = await create_tenant(client, superuser_headers, {"name": "ListCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@listco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@listco.com", "HR123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("list_test.txt", TXT_CONTENT, "text/plain")},
    )
    doc_id = up.json()["id"]

    lst = await client.get("/api/v1/documents/", headers=h)
    assert lst.status_code == 200
    ids = [d["id"] for d in lst.json()]
    assert doc_id in ids


@pytest.mark.asyncio
async def test_get_document_by_id(client: AsyncClient, superuser_headers: dict):
    """可以用 id 查詢單一文件"""
    t = await create_tenant(client, superuser_headers, {"name": "GetCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@getco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@getco.com", "HR123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("get_test.txt", TXT_CONTENT, "text/plain")},
    )
    doc_id = up.json()["id"]

    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_hr_can_delete_own_document(client: AsyncClient, superuser_headers: dict):
    """HR 可以刪除自己上傳的文件"""
    t = await create_tenant(client, superuser_headers, {"name": "DelCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@delco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@delco.com", "HR123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("del_test.txt", TXT_CONTENT, "text/plain")},
    )
    doc_id = up.json()["id"]

    del_resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=h)
    assert del_resp.status_code == 200

    get_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=h)
    assert get_resp.status_code in [404, 410]


@pytest.mark.asyncio
async def test_viewer_cannot_upload(client: AsyncClient, superuser_headers: dict):
    """Viewer 角色無法上傳文件"""
    t = await create_tenant(client, superuser_headers, {"name": "ViewCo"})
    await create_user(client, superuser_headers, {
        "email": "viewer@viewco.com", "password": "View123!",
        "full_name": "Viewer", "role": "viewer", "tenant_id": t["id"],
    })
    h = await login_user(client, "viewer@viewco.com", "View123!")

    resp = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("v.txt", TXT_CONTENT, "text/plain")},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_tenant_document_inaccessible(client: AsyncClient, superuser_headers: dict):
    """跨租戶文件存取應被拒絕"""
    ta = await create_tenant(client, superuser_headers, {"name": "CrossA"})
    tb = await create_tenant(client, superuser_headers, {"name": "CrossB"})

    for t, email in [(ta, "hr@crossa.com"), (tb, "hr@crossb.com")]:
        await create_user(client, superuser_headers, {
            "email": email, "password": "HR123!",
            "full_name": "HR", "role": "hr", "tenant_id": t["id"],
        })

    ha = await login_user(client, "hr@crossa.com", "HR123!")
    hb = await login_user(client, "hr@crossb.com", "HR123!")

    up = await client.post(
        "/api/v1/documents/upload", headers=ha,
        files={"file": ("secret.txt", b"top secret", "text/plain")},
    )
    doc_id = up.json()["id"]

    cross = await client.get(f"/api/v1/documents/{doc_id}", headers=hb)
    assert cross.status_code in [403, 404]


@pytest.mark.asyncio
async def test_oversized_file_rejected(client: AsyncClient, superuser_headers: dict):
    """超過 MAX_FILE_SIZE 的文件應被拒絕"""
    t = await create_tenant(client, superuser_headers, {"name": "SizeCo"})
    await create_user(client, superuser_headers, {
        "email": "hr@sizeco.com", "password": "HR123!",
        "full_name": "HR", "role": "hr", "tenant_id": t["id"],
    })
    h = await login_user(client, "hr@sizeco.com", "HR123!")

    # 52MB > 預設 50MB 上限
    big = b"x" * (52 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/documents/upload", headers=h,
        files={"file": ("big.txt", big, "text/plain")},
    )
    assert resp.status_code in [400, 413]
