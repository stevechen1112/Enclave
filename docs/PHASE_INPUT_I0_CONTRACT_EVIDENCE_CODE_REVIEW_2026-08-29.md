# Input I0 — Contract 與證據凍結 Code Review

日期：2026-08-29
結論：`PASS`
下一階段：`Input I1 ALLOWED`
部署狀態：`NOT DEPLOYED`

## 1. Review 範圍與身分

- Source baseline：`d85b1503e1058ec4865d3f21a4477a363205c351` 加上本次未提交 I0 working-tree patch。
- DB schema head：`p5_cost_guardrails_001`；I0 無 migration、無資料表變更。
- Frontend canonical route contract hash：`5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f`，I0 未改 frontend canonical routes。
- Input contract version：`input-capabilities.v1`。
- Input registry SHA-256：`90222a30392996f896b4d8bef0e37f79a2b8d13d0ee1583577ba7c24d2a4a30e`。
- Golden corpus SHA-256：`3cd9a619569244fe6886e1b9120ae311019143af4f137a61e93077c13f28f6e4`。
- 新增 authenticated API：`GET /api/v1/knowledge/input-capabilities`。

本 Review 只判定 I0 contract／evidence freeze 是否完成，不把 I1 UX、I2 通用續傳、I3 實體裝置、I4/I5 品質或 I7 live capacity 視為已完成。

## 2. 交付對照

| I0 交付 | 實作／證據 | 判定 |
|---|---|---|
| 單一 capability registry | `app/platform/intake/capabilities.py` 統一文件、音訊、影片 extension、MIME、asset kind、capability、限制、evidence state 與 provider/degradation | PASS |
| Runtime discovery API | authenticated tenant-bound response model；回傳 contract/hash/policy/formats/sources/providers/adapters | PASS |
| Parser／route parity | `SUPPORTED_FORMATS`、knowledge asset audio/video、video route 與 ingestion adapters 改由 registry 派生 | PASS |
| Contract snapshot | `artifacts/input/i0_input_contract_snapshot.json`；測試反向比對 runtime registry、adapter、provider keys 與 OpenAPI route | PASS |
| Sealed corpus | 7 個 hashed entries、7 個 coverage axes、6 個明示缺口；verifier 驗 hash、bytes、path containment 與 corpus digest | PASS |
| Telemetry baseline | `INPUT_I0_TELEMETRY_BASELINE_2026-08-28.md`；區分已有 metrics primitives 與 `NOT_MEASURED` Input SLO | PASS |
| 歷史宣稱對帳 | `CAPABILITY_CLAIMS.md`、`PIPELINE_STRENGTH_MAP.md` 已加歷史時點警示 | PASS |
| Pack independence | Input platform 新增程式無 `app.packs`、MKA endpoint 或 MKA model import | PASS |

## 3. Review 發現與處置

| 發現 | 風險 | 處置 | 狀態 |
|---|---|---|---|
| 文件、音訊、影片原有多份格式清單 | parser、API 與 UI 容易漂移 | 建立 server-owned registry，既有核心路徑改由 registry 派生 | CLOSED |
| Adapter discovery 原本只有 key，審計若讀 private map 會破壞封裝 | contract API 依賴內部實作 | 新增 immutable `adapters` snapshot property | CLOSED |
| 只看 config 可能把 optional parser/provider 寫成健康 | 假完成／錯誤 UI 宣稱 | 分開 `processing_status`、`runtime_verified` 與 degradation reasons；provider 未探測一律不稱 healthy | CLOSED |
| API key 用於判斷 provider 是否 configured | secret 可能被 discovery response 洩漏 | 只回傳狀態與安全 detail；自動測試以 sentinel 驗證 secret 不出現在 JSON | CLOSED |
| Manifest path 或 hash 可被竄改 | corpus evidence 不可重放 | verifier fail-closed 驗 repository containment、SHA-256、bytes 與 aggregate digest | CLOSED |
| 新版 FastAPI router inventory 含 lazy included router | 直接讀 `route.path` 的測試不可靠 | 改由完整 OpenAPI path 驗證 public route | CLOSED |
| 測試容器將 pip cache 寫入 workspace | 可能污染工作樹 | 最終 run 將 cache 指向容器 `/tmp`；誤觸的受控 cache 內容已精確還原 | CLOSED |

## 4. 安全、可靠性與相容性

- API 要求 active user，response 綁定 tenant identity；沒有新增匿名能力探測面。
- Response 不包含 API key、password、token 或 storage secret。
- Registry 在 module import 時拒絕重複 extension。
- 回傳 source declarations 使用 defensive copy，呼叫端不能改寫全域 registry。
- Corpus verifier 拒絕 `..` path escape、缺檔、hash/size mismatch、coverage 缺漏與未宣告 gap。
- 沒有 DB migration、durable-object rewrite、legacy route 移除或 Domain Pack 依賴變更。
- `generic_resumable_upload=false` 是刻意凍結的現況，不把 I2 能力提前宣稱為完成。
- 音訊 STT disabled、影片 disabled、OCR/parser dependency 不完整時，contract 會明示 disabled/degraded。

## 5. 驗證結果

| 驗證 | 結果 |
|---|---|
| Ruff（I0 新增與相鄰修改檔） | PASS |
| `git diff --check` | PASS；只有既有 Windows LF/CRLF warning |
| Golden corpus verifier | PASS；7 entries、7 coverage axes、6 declared gaps |
| I0 + parser/adapter/asset/capture/connector/video 擴大回歸 | **72 passed / 0 failed** |
| OpenAPI public route snapshot | PASS |
| Secret non-disclosure contract | PASS |
| Domain Pack dependency scan | PASS；0 個 I0 core → MKA import |

測試使用依 `requirements.lock.txt` 與 `requirements-test.lock.txt` 建立的一次性容器環境；依賴只放在容器 `/tmp`，測試後容器刪除。第一次 router inventory 測試暴露的是測試對 lazy router 型別的錯誤假設；改以 OpenAPI 驗證後完整重跑，最終結果為 72/72 PASS。

## 6. 保留風險與下一階段邊界

- Frontend 尚未消費 capability API，格式清單與硬編碼 summary 的收斂屬 I1。
- 一般檔案沒有 resumable upload；I0 只把此事實正式寫入 contract，實作屬 I2。
- 長時間錄音仍在 MKA；下沉屬 I3。
- Corpus 中音訊／影片目前是 contract-only evidence，真實工廠媒體品質屬 I5。
- 實體 iOS／Android、弱網、P5 capacity/degradation/soak 仍未執行，不得對外宣稱 PASS。
- 文件與 Connector 仍有 Legacy `Document` 相容投影，移除不在 I0 範圍。
- 本 patch 尚未 commit、build 或部署；production 仍是既有 release。

## 7. Gate 決定

I0 的唯一事實來源、runtime contract、sealed evidence、telemetry baseline、歷史宣稱邊界與回歸證據均已建立，沒有未關閉的資料遺失、租戶越權、假完成、migration 或核心反向依賴問題。

**Code Review：PASS。Input I1 可以開始；I2 及後續能力不得提前標示完成。**
