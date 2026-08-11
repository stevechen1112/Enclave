# EQ-100 場景 QR 註冊資料（SceneRegistry 設定用）

**用途**：劇本 B 任務 B1「掃碼進入設備場景」。請管理員依下列資料在 SceneRegistry 建立場景，系統產生 opaque token 後，以 QR 產生器（任一線上工具）將掃碼 URL 做成 QR Code 列印。

## 場景一：EQ-100 機台（正式測試用）

| 欄位 | 值 |
|------|-----|
| scene_type | `equipment` |
| label | EQ-100 高速捲繞機（二廠 A 產線） |
| equipment_id | `EQ-100-01` |
| department | 製造部／二廠 |
| line | A 產線 |
| default_module | `incident_handover` |
| linked_documents | D02（SOP）、D03a–c（維修紀錄）、D07b（安全指引） |
| active | true |

## 場景二：未註冊對照 QR（fail-closed 測試用）

- 用任意文字（如 `https://example.com/not-a-scene`）產生一張 QR。
- 預期行為：掃描後系統顯示「無法識別的場景」，**不得**亂猜場景或直接進入一般問答（依測試劇本 B1 對照測試）。

## QR 內容格式

依系統實作，QR 內容為帶 opaque token 的 URL，例如：

```
https://<測試主機>/scene/<opaque_token>
```

實際 token 由 SceneRegistry 建立場景後產生，請勿自行編造。

## 列印建議

- 尺寸 ≥ 5 × 5 cm，貼於壓克力板（模擬機台銘牌）。
- 正式測試時貼於測試場地牆面或設備模型上，讓受測者「走到機台旁掃碼」。
