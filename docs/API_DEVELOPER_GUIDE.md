# Enclave API 開發者文件

> Version: 1.0 | Base URL: `https://app.yourdomain.com/api/v1`
> OpenAPI Spec: `https://app.yourdomain.com/api/v1/openapi.json`

---

## 目錄

1. [快速開始](#1-快速開始)
2. [認證](#2-認證)
3. [API 總覽](#3-api-總覽)
4. [常用端點範例](#4-常用端點範例)
5. [Rate Limit 說明](#5-rate-limit-說明)
6. [錯誤處理](#6-錯誤處理)
7. [Webhook 事件](#7-webhook-事件)
8. [SDK 與程式庫](#8-sdk-與程式庫)
9. [最佳實踐](#9-最佳實踐)
10. [API 版本策略](#10-api-版本策略)

---

## 1. 快速開始

### 取得 API Token

```bash
# 1. 登入取得 JWT Token
curl -X POST https://app.yourdomain.com/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=your@email.com&password=yourpassword"

# Response:
# {
#   "access_token": "eyJhbGciOiJIUzI1NiIs...",
#   "token_type": "bearer"
# }
```

### 發送第一個請求

```bash
# 2. 使用 Token 呼叫 API
curl -X GET https://app.yourdomain.com/api/v1/users/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

## 2. 認證

### 2.1 JWT Bearer Token

所有 API 請求（除公開端點外）需要在 Header 帶上 JWT Token：

```
Authorization: Bearer <access_token>
```

Token 預設有效期為 **480 分鐘（8 小時）**。到期後需重新登入。

### 2.2 SSO 登入

支援 Google 和 Microsoft SSO（需租戶管理員事先設定）：

```bash
# 取得 SSO 登入 URL
curl -X POST https://app.yourdomain.com/api/v1/auth/sso/initiate \
  -H "Content-Type: application/json" \
  -d '{"provider": "google", "tenant_id": "your-tenant-id"}'
```

### 2.3 Service Token（內部服務）

微服務間通訊使用 `X-Service-Token` Header：

```
X-Service-Token: <service_token>
```

---

## 3. API 總覽

### 公開端點（無需認證）

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/auth/login` | 登入 |
| `GET` | `/public/branding` | 取得登入頁品牌設定 |
| `GET` | `/subscription/plans` | 取得方案列表 |
| `GET` | `/regions/regions` | 取得支援區域列表 |

### 使用者端點

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/users/me` | 取得個人資料 |
| `PUT` | `/users/me` | 更新個人資料 |
| `POST` | `/chat/` | 發送聊天訊息 |
| `GET` | `/chat/conversations` | 列出對話記錄 |
| `GET` | `/chat/conversations/{id}/messages` | 取得對話訊息 |
| `GET` | `/documents/` | 列出文件 |
| `GET` | `/kb/search` | 搜尋知識庫 |

### 管理員端點（Owner / Admin）

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/users/` | 列出公司成員 |
| `POST` | `/users/` | 建立使用者 |
| `PUT` | `/users/{id}` | 更新使用者 |
| `POST` | `/documents/upload` | 上傳文件 |
| `DELETE` | `/documents/{id}` | 刪除文件 |
| `GET` | `/audit/logs` | 稽核記錄 |
| `GET` | `/audit/usage/summary` | 用量摘要 |
| `GET` | `/company/branding` | 取得品牌設定 |
| `PUT` | `/company/branding` | 更新品牌設定 |
| `POST` | `/domains/` | 新增自訂域名 |
| `GET` | `/subscription/current` | 當前方案 |
| `GET` | `/subscription/usage/export` | 匯出用量 |

### 平台管理端點（Superuser Only）

| Method | Path | 說明 |
|--------|------|------|
| `GET` | `/admin/dashboard` | 平台總覽 |
| `GET` | `/admin/tenants` | 全租戶列表 |
| `GET` | `/admin/tenants/{id}/stats` | 租戶統計 |
| `PUT` | `/admin/tenants/{id}` | 更新租戶 |
| `GET` | `/admin/system/health` | 系統健康 |
| `GET` | `/analytics/trends/daily` | 每日趨勢 |
| `GET` | `/analytics/anomalies` | 異常偵測 |

---

## 4. 常用端點範例

### 4.1 聊天 — 發送問題

#### cURL

```bash
curl -X POST https://app.yourdomain.com/api/v1/chat/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "特休假怎麼計算？"
  }'
```

#### Python

```python
import httpx

BASE_URL = "https://app.yourdomain.com/api/v1"
TOKEN = "your_access_token"

headers = {"Authorization": f"Bearer {TOKEN}"}

# 發送問題
response = httpx.post(
    f"{BASE_URL}/chat/",
    headers=headers,
    json={"question": "特休假怎麼計算？"},
    timeout=30,
)

data = response.json()
print(f"回答：{data['answer']}")
print(f"來源：{data.get('sources', [])}")
```

#### JavaScript (Node.js)

```javascript
const BASE_URL = "https://app.yourdomain.com/api/v1";
const TOKEN = "your_access_token";

// 發送問題
const response = await fetch(`${BASE_URL}/chat/`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${TOKEN}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ question: "特休假怎麼計算？" }),
});

const data = await response.json();
console.log("回答:", data.answer);
console.log("來源:", data.sources);
```

### 4.2 文件上傳

#### cURL

```bash
curl -X POST https://app.yourdomain.com/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@company_rules.pdf"
```

#### Python

```python
with open("company_rules.pdf", "rb") as f:
    response = httpx.post(
        f"{BASE_URL}/documents/upload",
        headers=headers,
        files={"file": ("company_rules.pdf", f, "application/pdf")},
    )

doc = response.json()
print(f"文件 ID: {doc['id']}")
print(f"狀態: {doc['status']}")  # pending → processing → processed
```

### 4.3 知識庫搜尋

```bash
curl -X GET "https://app.yourdomain.com/api/v1/kb/search?q=加班費&top_k=5" \
  -H "Authorization: Bearer $TOKEN"
```

### 4.4 用量匯出

```bash
# JSON 格式
curl -X GET "https://app.yourdomain.com/api/v1/subscription/usage/export?format=json" \
  -H "Authorization: Bearer $TOKEN"

# CSV 格式
curl -X GET "https://app.yourdomain.com/api/v1/subscription/usage/export?format=csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o usage_report.csv
```

### 4.5 完整 Python SDK 範例

```python
"""Enclave API Client 範例"""

import httpx
from typing import Optional


class EnclaveClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30)
        self.token = self._login(email, password)
        self.client.headers["Authorization"] = f"Bearer {self.token}"

    def _login(self, email: str, password: str) -> str:
        resp = self.client.post(
            f"{self.base_url}/auth/login",
            data={"username": email, "password": password},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def ask(self, question: str) -> dict:
        """發送 AI 問答"""
        resp = self.client.post(
            f"{self.base_url}/chat/",
            json={"question": question},
        )
        resp.raise_for_status()
        return resp.json()

    def search_kb(self, query: str, top_k: int = 5) -> list:
        """搜尋知識庫"""
        resp = self.client.get(
            f"{self.base_url}/kb/search",
            params={"q": query, "top_k": top_k},
        )
        resp.raise_for_status()
        return resp.json()

    def upload_document(self, filepath: str) -> dict:
        """上傳文件"""
        with open(filepath, "rb") as f:
            resp = self.client.post(
                f"{self.base_url}/documents/upload",
                files={"file": f},
            )
        resp.raise_for_status()
        return resp.json()

    def list_documents(self) -> list:
        """列出文件"""
        resp = self.client.get(f"{self.base_url}/documents/")
        resp.raise_for_status()
        return resp.json()

    def get_usage(self) -> dict:
        """取得用量摘要"""
        resp = self.client.get(f"{self.base_url}/audit/usage/summary")
        resp.raise_for_status()
        return resp.json()


# 使用範例
if __name__ == "__main__":
    client = EnclaveClient(
      base_url="https://app.yourdomain.com/api/v1",
        email="admin@example.com",
        password="your_password",
    )

    # 提問
    answer = client.ask("員工請病假需要什麼證明？")
    print(answer)

    # 搜尋
    results = client.search_kb("特休假")
    for r in results:
        print(r)
```

---

## 5. Rate Limit 說明

### 限制規則

| 類型 | 上限 | 適用範圍 |
|------|------|---------|
| 全域（Per IP） | 200 req/min | 所有端點 |
| Per User | 60 req/min | 已認證使用者 |
| Per Tenant | 300 req/min | 全租戶加總 |
| Chat API | 20 req/min | `/chat/` |
| Auth API | 10 req/min | `/auth/` |

### Rate Limit Headers

每個回應會包含以下 Header：

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1706889600
```

### 超過限制

當超過 Rate Limit 時，API 回傳 `429 Too Many Requests`：

```json
{
  "detail": "Rate limit exceeded. Please retry after 60 seconds."
}
```

### 最佳實踐

- 實作指數退避（Exponential Backoff）
- 監控 `X-RateLimit-Remaining` Header
- 批量操作使用合理間隔
- Chat API 回應較慢，設定較長 timeout（30s）

---

## 6. 錯誤處理

### HTTP 狀態碼

| 狀態碼 | 說明 | 常見原因 |
|--------|------|---------|
| 200 | 成功 | — |
| 201 | 建立成功 | POST 建立資源 |
| 400 | 請求錯誤 | 參數格式錯誤 |
| 401 | 未認證 | Token 遺失或過期 |
| 403 | 權限不足 | 角色不足以執行操作 |
| 404 | 資源不存在 | ID 錯誤或無權存取 |
| 409 | 衝突 | 資源已存在（如重複 Email） |
| 421 | 區域錯誤 | Tenant 不在此區域 |
| 422 | 驗證失敗 | 請求 Body 格式錯誤 |
| 429 | 超過限制 | Rate Limit |
| 500 | 伺服器錯誤 | 聯繫技術支援 |

### 錯誤回應格式

```json
{
  "detail": "Error description message"
}
```

部分端點會回傳更詳細的錯誤：

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## 7. Webhook 事件（規劃中）

> 以下 Webhook 功能為未來擴充規劃，尚未實作。

### 規劃中的事件

| 事件 | 觸發時機 | Payload 範例 |
|------|---------|-------------|
| `document.processed` | 文件處理完成 | `{document_id, status, chunk_count}` |
| `quota.warning` | 配額達告警閾值 | `{tenant_id, resource, usage_pct}` |
| `quota.exceeded` | 配額超限 | `{tenant_id, resource}` |
| `user.created` | 新使用者建立 | `{user_id, email, role}` |
| `tenant.suspended` | 租戶被停權 | `{tenant_id, reason}` |

### Webhook 安全機制（規劃）

- 每個 Webhook 請求附帶 `X-UniHR-Signature` Header
- 使用 HMAC-SHA256 簽章驗證
- 推薦使用 HTTPS endpoint

---

## 8. SDK 與程式庫

### 官方支援

| 語言 | 套件 | 狀態 |
|------|------|------|
| Python | `unihr-python` | 規劃中 |
| JavaScript/TypeScript | `@unihr/sdk` | 規劃中 |

### 目前建議

使用任何 HTTP 客戶端配合本文件的 API 說明即可：

- **Python**: `httpx` 或 `requests`
- **JavaScript**: `fetch` 或 `axios`
- **Go**: `net/http`
- **Java**: `HttpClient`

### OpenAPI 自動生成

Enclave 基於 FastAPI，自動產生完整的 OpenAPI 3.0 規格：

```bash
# 下載 OpenAPI spec
curl https://app.yourdomain.com/api/v1/openapi.json -o openapi.json

# 使用 openapi-generator 生成 SDK
npx @openapitools/openapi-generator-cli generate \
  -i openapi.json \
  -g python \
  -o python-sdk/
```

---

## 9. 最佳實踐

### 9.1 Token 管理

- 不要將 Token 硬編碼在程式碼中
- 使用環境變數存放 Token
- Token 過期前主動重新登入
- 在伺服器端執行 API 呼叫，避免前端暴露 Token

### 9.2 錯誤處理

```python
import httpx

try:
    response = client.post(f"{BASE_URL}/chat/", json={"question": "..."})
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    if e.response.status_code == 429:
        # Rate limit — 等待重試
        retry_after = int(e.response.headers.get("Retry-After", 60))
        time.sleep(retry_after)
    elif e.response.status_code == 401:
        # Token 過期 — 重新登入
        token = login()
    else:
        raise
```

### 9.3 效能建議

- 使用 HTTP/2（FastAPI 支援）
- 啟用 Keep-Alive 連線重用
- Chat API 設定 30 秒以上 timeout
- 批量查詢時加入 1-2 秒間隔

### 9.4 安全建議

- 所有 API 呼叫使用 HTTPS
- 定期輪替 Token
- 限制 Token 作用範圍（不使用 Superuser Token 做日常操作）
- 記錄 API 呼叫日誌以供稽核

---

## 10. API 版本策略

### 目前版本

- **v1** — 穩定版（目前使用）
- **v2** — 規劃中（向下相容）

### 版本切換

```
# v1（目前）
https://app.yourdomain.com/api/v1/...

# v2（未來）
https://app.yourdomain.com/api/v2/...
```

### Deprecation Header

當 API 版本即將棄用時，回應會包含：

```
X-API-Version: v1
X-API-Deprecated: true
X-API-Sunset-Date: 2027-01-01
```

### 版本資訊端點

```bash
curl https://app.yourdomain.com/api/versions

# Response:
# {
#   "versions": {
#     "v1": {"status": "stable", "path": "/api/v1"},
#     "v2": {"status": "beta", "path": "/api/v2"}
#   },
#   "current": "v1",
#   "latest": "v2"
# }
```
