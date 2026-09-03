# Input I9-1 媒體正規化與錯誤分類 — Code Review

日期：2026-09-03

結果：PASS

範圍：音訊 codec 矩陣、失敗 taxonomy、重試判斷、成功後錯誤清理

## Review 結論

未發現阻擋進入 I9-2 的 correctness、tenant isolation 或原檔保存問題。

Review 過程發現 Windows 沒有 `signal.SIGKILL` 常數，已改為跨平台 fallback 值 9 並重新驗證。另補強帶有 code 但未宣告 retryable 的例外，使其預設 fail closed，不會因布林轉換產生分類矛盾。

## 已確認行為

- `pcm_s24le`、`pcm_s32le`、float PCM 等常見錄音 codec 可通過 probe。
- 所有來源仍保留原始內容；轉錄前由 FFmpeg 轉成受控單聲道 MP3 chunk。
- `MediaPolicyError` 是永久錯誤，不進行無效 Celery retry。
- timeout、SIGKILL 及可恢復媒體命令錯誤被分類為可重試資源／暫時錯誤。
- persistence 同時保存安全 user message 與受限 technical message。
- failed job 再次進入 running，或最後進入 review／ready 時，active error 會清除；舊失敗仍可由事件歷史追溯。
- 未修改 tenant scope、ACL、原始來源或人工核准規則。

## 驗證證據

```text
pytest tests/test_input_i5_media_productization.py
       tests/test_ingestion_failures.py
       tests/test_ingestion_orchestrator.py -q

30 passed
```

另執行本階段四個 Python 模組的 `compileall`，通過。

## 剩餘風險與後續階段

- Production 實際環境仍使用舊映像，必須在 I9-7 部署後才會接受 `pcm_s24le`。
- Worker SIGKILL、queue 隔離與 stale job recovery 不屬於本階段，移交 I9-2。
- 使用者可見錯誤與首頁狀態文案移交 I9-4。
