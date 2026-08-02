# Security Findings Register

本文件由 `scripts/security_findings_gate.py` 更新。
**Critical/High 關閉需掃描證據；外部滲透測試另列，不得用本腳本替代。**

- Last scan: `2026-08-01T04:29:46.514032+00:00`
- Artifact: `artifacts\security_scan_last_run.json`
- Open Critical/High: **0**
- Gate: `PASS`

| ID | Severity | Title | Owner | Status | Evidence |
|----|----------|-------|-------|--------|----------|
| SEC-000 | — | No Critical/High from automated dependency+SAST+API smoke | platform | closed | artifacts\security_scan_last_run.json |

## 流程

1. `python scripts/security_findings_gate.py`
2. 修復 open Critical/High 後重跑至 Gate=PASS
3. Phase 0 / Beta 安全勾選僅在 Gate=PASS 時允許
4. 外部滲透測試完成後另增 `SEC-PENTEST-*` 列並勾 GA 人工項

## 相關人工閘門（本腳本不關閉）

- 外部滲透測試
- 模型／依賴商用授權法律審查
