# Enclave Mobile (Phase 12)

React Native + Expo 地端企業 AI 知識大腦行動應用程式。

## 環境需求

| 工具 | 版本 |
|------|------|
| Node.js | ≥ 18 |
| npm / yarn | npm ≥ 9 |
| Expo CLI | `npm install -g expo-cli` |
| Expo Go App | iOS / Android |

---

## 快速開始

### 1. 安裝依賴

```bash
cd mobile
npm install
```

### 2. 設定伺服器 IP

編輯 `src/config.ts`，將 `API_BASE_URL` 改為後端伺服器的實際網路位址：

```ts
// Expo Go 使用手機時不能用 localhost，須改用電腦區域網路 IP
export const API_BASE_URL = 'http://192.168.x.x:8000/api/v1'
```

> **提示**：在 Windows 上執行 `ipconfig`，找 `IPv4 位址` 那行。

### 3. 確保後端允許區域網路連線

確認 CORS 設定中已加入手機 IP，或開放所有來源（僅限開發環境）。

### 4. 啟動開發伺服器

```bash
npm start
# 或指定平台
npm run android
npm run ios
```

用手機開啟 **Expo Go**，掃描終端機顯示的 QR Code。

---

## 專案結構

```
mobile/
├── App.tsx                     # 入口，掛載 AuthProvider + AppNavigator
├── app.json                    # Expo 設定
├── package.json
├── tsconfig.json
├── babel.config.js
└── src/
    ├── config.ts               # 伺服器 URL 設定
    ├── types.ts                # 共用 TypeScript 型別（與 web 一致）
    ├── api.ts                  # Axios client + API 函式
    ├── auth.tsx                # AuthContext（SecureStore 取代 localStorage）
    ├── navigation/
    │   ├── AppNavigator.tsx    # Root Stack（Login / Main）
    │   └── MainNavigator.tsx   # Bottom Tabs（AI問答/內容生成/文件/審核）
    ├── screens/
    │   ├── LoginScreen.tsx     # 登入畫面
    │   ├── ChatListScreen.tsx  # 對話列表（新增 / 刪除）
    │   ├── ChatDetailScreen.tsx# 對話詳情（SSE 串流）
    │   ├── DocumentsScreen.tsx # 文件列表 + 上傳（expo-document-picker）
    │   ├── GenerateScreen.tsx  # 內容生成（SSE 串流，5 種模板）
    │   └── ReviewQueueScreen.tsx # 審核佇列（read-only，P12-2 補完）
    └── components/
        └── LoadingScreen.tsx   # 全屏 loading fallback
```

---

## API 接線對照表（P12-1）

| 功能 | Web 路由 | Mobile 畫面 | Endpoint |
|------|----------|-------------|---------|
| 登入 | `/login` | `LoginScreen` | `POST /auth/login/access-token` |
| 取得使用者 | — | auth context | `GET /users/me` |
| 對話列表 | ChatPage 左欄 | `ChatListScreen` | `GET /chat/conversations` |
| 對話訊息 | ChatPage 右欄 | `ChatDetailScreen` | `GET /chat/conversations/{id}/messages` |
| SSE 串流問答 | ChatPage | `ChatDetailScreen` | `POST /chat/chat/stream` |
| 文件列表 | DocumentsPage | `DocumentsScreen` | `GET /documents/` |
| 文件上傳 | DocumentsPage | `DocumentsScreen` | `POST /documents/upload` |
| 內容生成 SSE | GeneratePage | `GenerateScreen` | `POST /generate/stream` |
| 審核佇列 | ReviewQueuePage | `ReviewQueueScreen` | `GET /agent/review` |

---

## Phase 12 計劃

| 版本 | 功能 |
|------|------|
| **P12-1** ✅ | 專案骨架、Login、Chat（SSE）、Documents（上傳）、Generate（SSE）、ReviewQueue（唯讀） |
| P12-2 | ReviewQueue 核准/拒絕操作、ProgressDashboard、Export DOCX/PDF |
| P12-3 | Push Notification（審核通知）、離線快取（AsyncStorage）|
| P12-4 | 生物辨識解鎖、App Store / Play Store 發布設定 |

---

## Token 安全

行動端使用 `expo-secure-store` 加密儲存 JWT token（iOS 使用 Keychain，Android 使用 Keystore），
取代 web 端的 `localStorage`。
