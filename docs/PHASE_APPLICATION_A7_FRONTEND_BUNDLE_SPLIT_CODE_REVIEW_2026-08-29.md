# Phase Application A7：前端 Bundle 拆分 Code Review

**日期：** 2026-08-29
**結果：** PASS

## 完成內容

- 刪除單一 `mkaBundle`。
- 建立 `workflowBundle`，只擁有 Job、Task、Form、Approval 共用路由。
- 建立 `salesQuoteBundle`，只擁有報價 redirect route。
- 建立 `trainingKnowhowBundle`，只擁有 know-how list、interview、detail routes。
- 後端 UI manifest 的 bundle key 與 route key 同步改為 `workflow.*`、`sales_quote.*`、`training_knowhow.*`。
- 異常與 8D 沒有複製空 UI bundle；它們透過共享 Workflow task route 呈現，application handler 仍獨立。

## Code Review

- Bundle registry 仍強制 route key 必須以 bundle key 為 namespace，且跨 bundle 不得重複。
- Server bootstrap 未提供某一 bundle manifest 時，該 bundle 產生 0 routes。
- Public URL 保持 `/job`、`/forms/*`、`/approvals`、`/quote`、`/knowhow/*`，未破壞 bookmark。

## 驗證

```text
TypeScript --noEmit                         PASS
Frontend module registry                    9 passed
Backend Pack/bootstrap/boundary             34 passed
```

## Gate

A7 通過。A8 尚需執行完整物理移除矩陣、全量回歸與瀏覽器驗收，完成前不宣稱整體重構收工。
