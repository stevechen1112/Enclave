# 仍開放閘門（整份計畫未閉環項）

同步來源：`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`、`docs/PLAN_PROGRESS.md`、`artifacts/plan_progress_last_run.json`。  
能力啟用／增量價值閘門（CV-*）：見 `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`（與下方商業 GA 人工閘門互補；舊 checkbox PASS 不自動等同 CV PASS）。

> **✅ CV-INT 已 PASS（2026-08-02 重跑）**：B1 正式 KB 切換 DeepDOC + B2 重解析後，動態查核 0 違規（正式 KB `layout_recognize=DeepDOC`，7 份宣稱 deepdoc 的文件與上游一致）。靜態掃描仍為 0；`tests/test_label_integrity_gate.py` 防回歸。
>
> 仍開放的能力閘門見 `CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` §7。  
> 2026-08-02 更新：能力啟用計畫可自動項已跑完。C2 LOCAL_FS **BLOCKED**；CV-RF-02／04／PH-05／WK-05 價值 **NO_VALUE**（WK-05 接線 PASS）；進階能力預設 OFF。  
> 剩餘僅人工閘門：外部滲透／法律／DR；SP／Drive OAuth 本機 SKIP。
>
> ```bash
> python scripts/eval_label_integrity.py     # 需 POSTGRES_* 與 RAGFLOW_* 環境變數
> ```

**施工約定**：目標為整份計畫完成時，代理人應連續推進；不要分段詢問是否繼續。  
僅在需要使用者提供外部憑證／簽核時中斷。

```bash
python scripts/plan_progress_gate.py --write-md --strict
```

## 目前狀態（自動閘門）

- 計畫 checkbox：**47/48**
- 可驗證 code：**100% (32/32)**
- false_green：**0**
- 剩餘 human gate：**1**（外部滲透）
- 本機階段 SKIP：SharePoint / Google Drive OAuth

## 不可代勞（需外部人／客戶／憑證）

| ID | 項目 | 計畫勾選 | 為何無法純程式關閉 | 證據位址 |
|----|------|----------|-------------------|----------|
| HG-PENTEST | 外部滲透測試 | `[ ]` | 需獨立第三方／授權範圍 | `FINDINGS_REGISTER` → 完成後加 `SEC-PENTEST-*` |
| HG-OAUTH-SP | SharePoint Online 連接器 | **SKIP（本機階段）** | 本機開發先跳過；不阻斷閉環 | `DEV_OAUTH_SETUP.md`（日後恢復） |
| HG-OAUTH-GD | Google Drive 連接器 | **SKIP（本機階段）** | 同上 | 同上 |
| HG-LEGAL | 模型／依賴商用授權審查 | 計畫註記人工 | 法律／採購簽核 | `FINDINGS_REGISTER` |
| HG-DR-SIGN | 客戶現場 DR／安裝簽核 | 計畫註記人工 | 客戶環境演練簽名 | `artifacts/ops/*` |

> **2026-08-01**：本機階段跳過 SP／Drive OAuth；第一批連接器以 `nas_smb` 為準。  
> **唯一仍未勾的出口條件 checkbox**：外部滲透測試。  
> **DD P0／P1**：已完成（pytest 277+）。  
> **P2 進度**：…；code-review 修復：資源級 deny、watcher review 清舊索引、SSO tenant filter、deploy stop→migrate→up、憑證 Fernet 加密。  
> 剩餘人工閘門：外部滲透／法律／DR。

## 已可由自動化關閉（本輪已關）

| 項目 | 腳本 | Artifact |
|------|------|----------|
| Critical/High 依賴+SAST+API smoke | `security_findings_gate.py` | `security_scan_last_run.json`（open_CH=0） |
| Pilot RAGFlow E2E | `e2e_vertical_slice_full.py` | `pilot_e2e_last_run.json` |
| Retrieval Hit@K + ACL | `eval_retrieval_gate.py` | `retrieval_gate_last_run.json` |
| Wiki/Graph + live WeKnora | `eval_wiki_graph_quality.py` | `wiki_graph_eval_last_run.json` |
| Backup | `ops_lifecycle.py backup` | `artifacts/ops/backup_*.json` + `backups/` |

## 關閉滲透閘門的條件

1. 取得第三方滲透報告
2. 在 `docs/security/FINDINGS_REGISTER.md` 新增 `SEC-PENTEST-*`（closed 或 open 分列）
3. 將計畫 GA「外部滲透測試完成」勾選
4. 重跑 `plan_progress_gate.py --write-md --strict` → checkbox 48/48
