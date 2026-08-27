# UI/UX 體驗收斂與 Knowledge Workspace 計畫

**建立日期：** 2026-08-27
**前置架構：** 多租戶平台、Knowledge Core、多模態 Ingestion、Pack Runtime 皆已建立
**施工原則：** 不改變既有 API URL、ACL、KnowledgeUnit authority 或 Pack entitlement

## 1. 目標

本輪不重新設計產品架構，而是讓既有正確架構形成一致、可理解、可擴充的
使用體驗。使用者應能沿著同一條流程完成：

`加入來源 → 確認處理能力 → 查看進度 → 覆核證據 → 發布 → 搜尋與引用`

文件、表格、圖片、音訊與影片可保留各自的專業檢視器，但必須共用相同的
頁面骨架、狀態語言、證據入口、版本資訊與返回路徑。Domain Pack 可以增加
工作流程，不得重新定義全站導覽、基本元件或權限顯示規則。

## 2. 不可破壞邊界

- server bootstrap 仍是 capability、primary navigation 與 default home 權威。
- SourceAsset、IngestionJob、ReviewItem、EvidenceSpan、KnowledgeUnit release
  仍是資料與狀態權威；前端不得自行推導授權或發布完成。
- MKA 等 Pack 只能透過 module bundle 與 manifest 貢獻 UI。
- legacy evidence deep link 在退場 gate 通過前維持可用。
- 高風險、低信心、SOP 衝突與缺少 evidence 的內容不得因 UI 簡化而繞過覆核。

## 3. Phase 與完成定義

### UX-A：Design System 語意層

- 建立共用 Workspace page、Section panel、空狀態與 metadata 顯示元件。
- 統一卡片、欄位、按鈕、focus、觸控尺寸及 reduced-motion 行為。
- 元件必須有 accessibility contract 與單元測試。
- 完成後執行 tests、lint、build 與獨立 code review。

### UX-B：Knowledge Workspace

- Asset Library、Asset Detail、文件與影片專業頁共用來源身分與生命週期語言。
- Asset Detail 成為來源、處理、版本、證據與專業工具的主要銜接點。
- 空狀態、失敗重試、返回路徑與 deep link 行為一致。
- 完成後執行 tests、lint、build 與獨立 code review。

### UX-C：多模態 Intake 與 Review

- Intake 清楚呈現來源方式、支援內容、資料分類與下一步。
- 檔案選擇支援拖放、多檔選取的產品契約；若後端仍為單檔請求，前端以
  可追蹤的逐檔佇列提交，不偽裝成原子批次。
- 上傳、解析、失敗與重試提供一致回饋。
- Review Workspace 在同一決策脈絡呈現候選內容、evidence、風險、衝突與
  publication contract。
- 完成後執行 tests、lint、build 與獨立 code review。

### UX-D：Pack UI contract 與角色驗證

- 定義 Pack bundle 可使用的 shell、route、navigation、empty/error 與
  permission guard 規格。
- 驗證現場人員、知識管理者、主管與系統管理員的主要任務。
- 關閉 Pack 後 navigation、route、action 必須 fail-closed。
- 執行完整 frontend regression、production build 與可用的 browser E2E。

## 4. 驗收情境

1. 知識管理者加入文件、錄音或影片後，可直接看到能力計畫與處理進度。
2. 失敗來源能在資產頁重試，不需回到專用工具尋找工作狀態。
3. 待審項目可從證據 deep link 返回相同來源與時間／頁面位置。
4. 一般使用者只能看到 server bootstrap 授權的功能。
5. MKA 未部署或租戶未啟用時，UI 不殘留 MKA 導覽或可操作入口。
6. 行動裝置的主要控制至少 44px，鍵盤 focus 可見，動畫遵守 reduced motion。

## 5. Code review gate

每個 Phase 的 review 文件至少記錄：變更範圍、發現與修正、權限影響、相容
影響、測試結果及是否允許進入下一 Phase。存在 Critical／High correctness、
authorization 或 evidence traceability 問題時不得進入下一階段。

## 6. 執行結果（2026-08-27）

| Phase | 結果 | Review |
|---|---|---|
| UX-A：Design System 語意層 | PASS | `docs/PHASE_UX_A_DESIGN_SYSTEM_CODE_REVIEW.md` |
| UX-B：Knowledge Workspace | PASS | `docs/PHASE_UX_B_KNOWLEDGE_WORKSPACE_CODE_REVIEW.md` |
| UX-C：多模態 Intake 與 Review | PASS | `docs/PHASE_UX_C_INTAKE_REVIEW_CODE_REVIEW.md` |
| UX-D：Pack UI contract 與角色驗證 | PASS | `docs/PHASE_UX_D_PACK_UI_CODE_REVIEW.md` |

完整結論見 `docs/FINAL_UIUX_EXPERIENCE_CONVERGENCE_CODE_REVIEW.md`。本輪程式
gate 通過；authenticated browser gate 因本機服務未啟動，保留為 staging
required，不以單元測試替代真實瀏覽器驗收。
