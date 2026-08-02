# 開發者 OAuth 設定（不是客戶憑證、也不是要把 Enclave 部署上雲）

## 先釐清架構

| 元件 | 跑在哪 |
|------|--------|
| Enclave API / DB / Celery / RAGFlow… | **你的本機**（或本機 Docker） |
| NAS 連接器 | **本機磁碟／SMB**（已可完整認證） |
| SharePoint Online / Google Drive | **微軟／Google 的雲端 SaaS**（資料與登入本來就在對方雲上） |

所以：本機開發 ≠ 不需要任何雲端。  
是「產品跑本機」，但若要測「連 SharePoint／Drive」，就必須打到對方的 OAuth／API 端點——這跟把 Enclave 架到 AWS/GCP 無關。

**純本機路徑**：只用 `nas_smb` 即可閉環 Pilot；SP／Drive 屬可選雲端來源。

開發／實驗室若要測 SP／Drive，用**你自己的** Azure / Google 測試應用。不需要真實客戶租戶，也不需要雲端主機跑 Enclave。

## SharePoint / Microsoft Graph

1. 到 [Azure Portal](https://portal.azure.com) → App registrations → New registration  
2. 名稱例如 `enclave-dev-sharepoint`  
3. Certificates & secrets → New client secret  
4. API permissions → Microsoft Graph → **Application** permissions：`Sites.Read.All`（或 `Sites.Selected`）→ Grant admin consent（對你自己的開發租戶）  
5. 寫入 `Enclave/.env`：

```env
SHAREPOINT_TENANT_ID=<你的 directory/tenant id>
SHAREPOINT_CLIENT_ID=<application (client) id>
SHAREPOINT_CLIENT_SECRET=<secret value>
SHAREPOINT_SITE_URL=https://<你的租戶>.sharepoint.com/sites/<測試站>
```

6. 執行：

```bash
python scripts/certify_connector.py --type sharepoint
```

通過條件：`token` + `graph` 探測成功 → `certified: true`。

## Google Drive

1. [Google Cloud Console](https://console.cloud.google.com/) → 建立專案 → OAuth client（Desktop 或 Web，redirect=`http://localhost:8000/oauth/callback`）  
2. 啟用 Google Drive API  
3. 寫入 `.env`：

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

4. 本機取得 refresh token（一次性瀏覽器同意）：

```bash
# 用 Enclave API 產生授權 URL
# POST /api/v1/connectors/oauth/authorize-url
# 瀏覽器登入你的 Google 測試帳號後，把 code 拿去
# POST /api/v1/connectors/oauth/token-exchange
# 將回傳存檔中的 refresh_token 寫入 .env：
GOOGLE_REFRESH_TOKEN=...
```

5. 執行：

```bash
python scripts/certify_connector.py --type google_drive
```

## 與「客戶正式環境」的差別

| | 開發者測試 App | 客戶正式上線 |
|--|----------------|--------------|
| 誰建立 | 你（開發者） | 客戶 IT / Entra 管理員 |
| 目的 | 關閉實驗室 OAuth 閘門 | 生產連線 |
| 本階段需要？ | **是（若要勾 SP/Drive certified）** | 之後才需要 |
