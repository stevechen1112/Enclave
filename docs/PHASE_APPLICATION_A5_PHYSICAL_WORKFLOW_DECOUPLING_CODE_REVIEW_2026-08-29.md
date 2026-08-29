# Phase Application A5：Workflow 物理脫鉤 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** Workflow handler resolution、場景 handler 搬移、Workflow/MKA repository 依賴反轉、application approval side effect

## 完成內容

- 新增 `WorkflowHandlerContribution`，handler 由 application Pack manifest 以版本、module key 與 import path 註冊。
- TaskEngine 改由 Pack Registry 解析 handler；核心檔案已刪除報價、異常、交接、8D、訓練與訪談實作。
- 建立通用 form-backed handler factory；它只知道 Workflow Form contract，不包含任何場景 form key。
- 報價、異常／交接、品質 8D、訓練／訪談 handler 已移至各自 application package。
- WorkflowRepository 從相容 facade 改為完整獨立實作，不再 import MKA model、MKA persistence 或 application Pack。
- MKARepository 反向繼承 WorkflowRepository，只保留 interaction 與 know-how application persistence，移除重複的 Form／Approval 實作。
- Know-how 簽核副作用移至 training application adapter，由 composition bridge 注入；Workflow approval 不再直接修改 KnowhowCardModel。
- 四個 application backend manifest 已成為獨立 Pack owner，MKA manifest 不再擁有四個 module key。

## Code Review 修正

### [Critical] TaskEngine 直接內建所有場景 handler

已完全移除。新增 architecture gate 逐字檢查 TaskEngine 不得出現場景 vocabulary、MKA persistence 或 application import。

### [Critical] WorkflowRepository 依賴大型 MKARepository

依賴方向已反轉。WorkflowRepository 是 Form／Approval 權威；MKARepository 繼承它並只增加 application 方法。catalog 中的 workflow compatibility bridge 已歸零。

### [High] Workflow approval 直接知道 know-how model

已改由 composition adapter 呼叫 training application 的 approval side-effect handler；核心只處理 form，未知 application object fail closed。

### [High] 一個 MKA deployment flag 綁住所有 handler

四個 Pack 現在可各自設定 deployment capability。測試關閉 sales_quote 後，quote handler 與 UI contribution 均消失，quality 與 training 不受影響。

## 驗證

```text
Workflow/application boundaries／Pack runtime／application lifecycle
TaskEngine／MKA persistence／P8 acceptance／experience bootstrap／job runtime

124 passed
```

- Python compile：PASS。
- TaskEngine application vocabulary scan：PASS（0 命中）。
- WorkflowRepository MKA import scan：PASS（0 命中）。
- 單一 application deployment exclusion：PASS。
- persistence、approval、quote journey 與 know-how lifecycle：PASS。
- 未變更 DB schema、public URL 或前端畫面。

## 尚未完成

- MKA compatibility shell 仍承載 know-how API、permissions、provisioning 與部分 capture worker contribution；A6 必須把這些移到 training／platform 所有者。
- 前端仍是單一 mkaBundle；A7 才會物理拆分。
- 尚未部署或進行瀏覽器驗收。

## Gate

A5 通過，可進入 A6；目前可以宣稱 Workflow Kernel 已物理脫離場景 handler 與 MKA persistence，但不能宣稱整個應用層物理拆包完成。
