# UniHR SaaS API 使用指南

## 快速開始

### 啟動服務

```bash
docker-compose up -d
```

服務將運行在 `http://localhost:8000`

### API 文檔

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 認證

### 1. 登入獲取 Token

```bash
curl -X POST "http://localhost:8000/api/v1/login/access-token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin"
```

**響應:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### 2. 使用 Token 進行認證

在所有後續請求中添加 Header：
```
Authorization: Bearer {access_token}
```

## API 端點

### 用戶管理

#### 獲取當前用戶資訊
```bash
GET /api/v1/users/me
```

#### 建立新用戶
```bash
POST /api/v1/users/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123",
  "tenant_id": "uuid-here",
  "full_name": "User Name",
  "is_superuser": false
}
```

### 租戶管理

#### 獲取租戶列表（僅 Superuser）
```bash
GET /api/v1/tenants/
```

**響應示例:**
```json
[
  {
    "id": "37667944-327d-4df2-af72-012d4ee52e51",
    "name": "Example Organization",
    "plan": "free",
    "status": "active",
    "created_at": "2026-02-06T07:10:23.700125Z",
    "updated_at": null
  }
]
```

#### 建立新租戶（僅 Superuser）
```bash
POST /api/v1/tenants/
Content-Type: application/json

{
  "name": "新公司",
  "plan": "pro",
  "status": "active"
}
```

**計畫類型:**
- `free`: 免費方案
- `pro`: 專業方案
- `enterprise`: 企業方案

**狀態:**
- `active`: 啟用中
- `suspended`: 已停用

#### 獲取特定租戶
```bash
GET /api/v1/tenants/{tenant_id}
```

#### 更新租戶資訊（僅 Superuser）
```bash
PUT /api/v1/tenants/{tenant_id}
Content-Type: application/json

{
  "plan": "enterprise"
}
```

## 測試範例

### 使用 curl 進行完整測試流程

```bash
# 1. 登入
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/login/access-token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin" | jq -r '.access_token')

# 2. 獲取當前用戶
curl -X GET "http://localhost:8000/api/v1/users/me" \
  -H "Authorization: Bearer $TOKEN"

# 3. 列出所有租戶
curl -X GET "http://localhost:8000/api/v1/tenants/" \
  -H "Authorization: Bearer $TOKEN"

# 4. 建立新租戶
curl -X POST "http://localhost:8000/api/v1/tenants/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"測試公司","plan":"pro","status":"active"}'
```

### 使用 Python requests

```python
import requests

BASE_URL = "http://localhost:8000/api/v1"

# 登入
response = requests.post(
    f"{BASE_URL}/login/access-token",
    data={"username": "admin@example.com", "password": "admin"}
)
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 獲取租戶列表
response = requests.get(f"{BASE_URL}/tenants/", headers=headers)
tenants = response.json()
print(tenants)
```

## 預設帳號

系統已預先建立以下帳號供測試：

- **Email**: admin@example.com
- **Password**: admin
- **權限**: Superuser
- **租戶**: Example Organization

## 權限說明

### Superuser
- 可以查看所有租戶
- 可以建立、更新任何租戶
- 可以為任何租戶建立用戶

### 一般用戶
- 只能查看自己所屬的租戶
- 只能為自己的租戶建立用戶
- 無法修改租戶資訊

## 錯誤處理

常見的 HTTP 狀態碼：

- `200`: 成功
- `400`: 請求錯誤（例如：email 已存在）
- `401`: 未認證（需要登入）
- `403`: 權限不足
- `404`: 資源不存在

## 下一步

接下來可以開發的功能：
1. 文檔上傳與管理 (S3/MinIO)
2. RAG 檢索系統 (pgvector + OpenAI)
3. 對話管理
4. 使用量追蹤與計費
