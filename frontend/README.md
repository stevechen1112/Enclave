# Enclave Web Frontend

Enclave 2.0 **Vault Control** 前端：企業知識控制面（地端 Pilot）。

React 19 + TypeScript + Vite + Tailwind CSS 4。

## 技術棧

| 項目 | 版本／說明 |
|------|------------|
| React | 19.x |
| TypeScript | 5.x |
| Vite | 7.x（dev proxy → `http://127.0.0.1:8000`） |
| Tailwind CSS | 4.x（`@tailwindcss/vite`） |
| React Router | 7.x |
| Recharts | 圖表（用量／問答品質） |

字型：Noto Sans TC + Source Serif 4（顯示）+ IBM Plex Mono；主題色為 slate + teal（非預設紫系）。

## 開發

```bash
cd frontend
npm install
npm run dev                          # 預設 vite.config port 3000
npm run dev -- --host 127.0.0.1 --port 5173   # 本機常用
npm run build
npm run preview
npm run test:e2e                     # Playwright（需另備環境）
```

API 請求走相對路徑 `/api/v1/*`，由 Vite proxy 轉到後端 `:8000`。

## 角色與主選單

| 角色 | 主選單 |
|------|--------|
| owner／admin | 總覽｜問答｜知識｜治理｜系統 |
| hr | 問答｜知識｜我的用量 |
| employee／viewer | 問答｜知識 |

創作（`/create`）與進階監控精靈在使用者選單／深連結，不佔主軸。

## 路由（現行 IA）

| 路由 | 說明 | 能力 |
|------|------|------|
| `/login` | 登入 | — |
| `/overview` | 總覽（待辦＋生命週期） | `admin_home` |
| `/ask` | 問答（證據面板、空答分類） | `ask` |
| `/knowledge/documents` | 文件列表／上傳 | `browse_knowledge` |
| `/knowledge/documents/:id` | 文件詳情 | `browse_knowledge` |
| `/knowledge/sources` | NAS／監控來源 | `manage_sources` |
| `/knowledge/review` | 審核佇列 | `review_queue` |
| `/knowledge/quality` | 結構化缺口／分類 | `governance` |
| `/governance/organization` | 組織／成員 | `governance` |
| `/governance/departments` | 部門 | `governance` |
| `/governance/audit` | 稽核 | `governance` |
| `/governance/insights` | 問答品質 | `governance` |
| `/system/modules` | 能力包狀態 | `system_ops` |
| `/system/health` | 健康／完整性 | `system_ops` |
| `/system/backup` | 備份／還原 | `system_ops` |
| `/system/deploy` | 部署模式 | `system_ops` |
| `/me/usage` | 我的用量 | `view_usage` |
| `/create` | 新建草稿 | `create_content` |
| `/create/reports` | 報告 | `create_content` |
| `/advanced/agent-wizard` | 監控進階精靈 | `manage_sources` |

舊路徑（`/documents`、`/connectors`、`/agent/review`、`/company`…）會 **redirect** 到上表。

能力對照實作：`src/navigation/capabilities.ts`。

## 目錄結構（摘要）

```
frontend/src/
├── App.tsx                 # 路由
├── auth.tsx                # JWT + /users/me
├── api.ts                  # Axios；documents.listAll 分頁累加
├── navigation/capabilities.ts
├── components/             # Layout、DomainChrome、PageHeader、ReadinessBanner…
├── pages/
│   ├── OverviewPage.tsx
│   ├── ChatPage.tsx / ask/
│   ├── DocumentsPage.tsx
│   ├── knowledge/          # Layout、Sources、Quality、Detail
│   ├── governance/         # Layout
│   ├── system/             # Modules、Health、Backup、Deploy
│   └── create/
└── index.css               # 設計 token（accent / wash / sidebar）
```

## Pilot 帳號（後端種子）

見根目錄 `README.md` §6.4。前端不內建帳號；登入後角色決定導覽。

## 設計／文案注意

- 使用者可見文案避免工程黑話（Agent／Embedding／P95…）
- 空知識庫時總覽應提示「尚未導入知識」，勿假「系統正常」
- 文件列表須用 `docApi.listAll()`，勿只打預設 `limit=100`

規劃原文：`docs/UIUX_2_0_PLAN.md`。
