# Phase Application A6：後端 Application Pack 拆分 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** sales_quote、incident_handover、quality_8d、training_knowhow deployable backend ownership

## 完成內容

- 四個既有場景各自擁有獨立 `app/packs/<application>/manifest.py`、handler 與 tenant eligibility。
- sales、incident、quality Pack 不再依賴 MKA compatibility shell。
- training Pack 的 persistence、know-how API、interview／audio API composition、knowledge provider、review provider、capture task descriptor 與 projector contribution 已移入 training package。
- `app.services.mka_persistence` 降為 deprecated import bridge，實作權威位於 training package。
- MKA manifest 不再擁有任何 application module key，也不再註冊 know-how provider、review provider、capture task 或 projector。
- composition 支援逐 Pack deployment flag；單一 Pack 可被排除，不影響其他 Pack。

## Code Review 發現與修正

### [Critical] Training Pack 的實作仍散落在 MKA shell

已將 persistence、API router、provider、review adapter 與 worker descriptors 移入 training package。舊 import path只 re-export，便於正式站相容觀察期。

### [High] 四個 Pack 都依賴 MKA，無法單獨部署

移除不必要 dependency。測試證明 `mka=false, sales_quote=true` 與 `mka=false, training_knowhow=true` 都能成功 composition；各自只提供自己的 runtime surface。

### [High] Training API 只靠 MKA aggregate entitlement

新增 training-owned router dependency，明確用 `training_knowhow` Pack 與 module context fail closed。

## 驗證

```text
Pack runtime／MKA persistence／TaskEngine／experience bootstrap／application lifecycle

97 passed
```

- 四 Pack composition：PASS。
- sales-only、training-only deployment：PASS。
- MKA shell disabled surface isolation：PASS。
- know-how persistence 與 review regression：PASS。
- DB schema 與 public URL 不變。

## 邊界

- `app.models.mka` 仍是歷史 aggregate model module；拆表名稱或 migration 不屬於安全移除的必要條件，ORM compatibility alias 仍保留。
- 三個舊 import path（knowhow endpoint、voice endpoint、`mka_persistence`）已列入機器可讀 deprecated bridge 清單並禁止擴增；A7/A8 路由搬移後歸零。
- MKA shell 尚承載共享現場 workspace UI manifest、job/scene/term 管理 API 與 provisioning compatibility；這些不是任一單一場景的私有功能，A7 會把共享 UI ownership 改為 Workflow bundle。
- 前端目前仍載入單一 mkaBundle，尚不能宣稱全端物理拆分完成。

## Gate

A6 通過，可以進入 A7。後端 application runtime 已可獨立部署與排除；下一個阻斷點是前端 bundle ownership。
