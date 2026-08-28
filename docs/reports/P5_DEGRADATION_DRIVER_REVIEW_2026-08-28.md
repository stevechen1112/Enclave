# P5 Degradation Driver Internal Code Review

日期：2026-08-28

Review 範圍：四種 live degradation driver、plan generator、provenance gate、測試與
runbook。這是 P5 內部工程批次 review，不是 Phase P5 最終 Code Review；正式 live
evidence 尚未執行，P6 entry 維持 CLOSED。

## 結論

程式與安全契約 review：PASS。

Live drill evidence：NOT RUN／DEDICATED HOST REQUIRED。

## Review findings 與處置

| Finding | 風險 | 處置 | 結果 |
|---|---|---|---|
| 任意 argv 可偽造 verify JSON | 假 PASS | 只接受同 commit、SHA-256 相符且位於固定目錄的 driver | CLOSED |
| Driver 可換用未綁定 integrity script | 跨租戶／job 證據可被替換 | `trusted_files` 強制鎖定 `run_p5_integrity_probe.py` 的 commit 與 hash | CLOSED |
| Queue 注入中途終止可能遺失 marker | 無法精準復原或誤清其他工作 | mutation 前先持久化唯一 marker 與 planned count | CLOSED |
| Queue recovery 可能粗暴清空 broker | 資料遺失 | 只允許 LREM 本次 marker，禁止 FLUSHDB／purge | CLOSED |
| Container 名稱可能指向其他 deployment | 誤傷 production | project＋service Compose labels 必須各唯一命中一個 container | CLOSED |
| Secret 可能落入 argv/transcript | 憑證洩漏 | password/token/secret/API key/Authorization flags fail closed；密碼只讀環境變數 | CLOSED |
| Probe 失敗後未恢復 | staging 長時間故障 | outer runner 無條件嘗試 recover 與 verify；中斷可重跑同 plan 觸發復原 | CLOSED |
| 單元測試可能被誤認為 live evidence | 錯誤放行 P5 | 文件與 gate 明確維持 execution_class=live 要求；目前四情境皆 NOT RUN | CLOSED |

## 驗證結果

- P5 regression：84 passed。
- Ruff：PASS。
- `git diff --check`：PASS。
- 新增負向測試：inline command、非隔離環境、driver commit mismatch、integrity
  trusted-file 缺失／hash mismatch、queue mid-fill journal、精準 marker recovery。
- 未在共用 staging／production host 執行 pause、quota mutation、queue fill 或 sidecar
  fault injection。

## 仍待 Phase gate 的項目

1. 獨立 Lite／Standard／Enterprise capacity evidence。
2. 四種 driver 在 PASS isolated environment 的 live reports。
3. Standard 72 小時 soak。
4. P5 evidence assembler 與 verifier PASS。
5. 完整 Phase P5 Code Review PASS。
