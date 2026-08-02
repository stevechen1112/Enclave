# Enclave Mobile（Experimental）

React Native + Expo 行動端子集。**非 Enclave 2.0 GA 路徑**——詳見同目錄 `EXPERIMENTAL.md`。

後端仍保留 `/api/v1/mobile`；Web 控制面為正式產品面（見根目錄與 `frontend/README.md`）。

## 環境需求

| 工具 | 版本 |
|------|------|
| Node.js | ≥ 18 |
| npm | ≥ 9 |
| Expo Go | iOS／Android |

## 快速開始

```bash
cd mobile
npm install
```

編輯 `src/config.ts`，將 `API_BASE_URL` 設為後端位址（手機無法用 `localhost`）：

```ts
export const API_BASE_URL = 'http://192.168.x.x:8000/api/v1'
```

Windows 可用 `ipconfig` 查 IPv4。確認後端 CORS 允許該來源（開發環境）。

```bash
npm start
# 或 npm run android / npm run ios
```

用 Expo Go 掃 QR Code。

## 功能對照（與 Web）

| 功能 | Web | Mobile | API |
|------|-----|--------|-----|
| 登入 | `/login` | `LoginScreen` | `POST /auth/login/access-token` |
| 問答 SSE | `/ask` | Chat 畫面 | `POST /chat/chat/stream` |
| 文件 | `/knowledge/documents` | `DocumentsScreen` | `/documents` |
| 生成 | `/create` | `GenerateScreen` | `/generate/stream` |
| 審核（唯讀／部分） | `/knowledge/review` | `ReviewQueueScreen` | `/agent/review` |

Mobile **未實作**完整 UI 2.0 IA（總覽／治理／系統等）。

## Token

使用 `expo-secure-store` 存 JWT（非 `localStorage`）。

## 狀態

| 項目 | 說明 |
|------|------|
| 產品定位 | Experimental；不宣稱 GA |
| CI／lockfile | 未達 Web 同等水準 |
| 後續 | 見歷史 Phase 12 計畫；優先級低於 Web Control Plane |
