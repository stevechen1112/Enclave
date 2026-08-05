# SaaS／託管租戶開戶（Sales-Led）

**最後更新**：2026-08-05  
**形態**：B 託管私有雲（每客一實例）為主；C 多租戶為 Phase 2  
**對齊**：`CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.10 WS-GTM-OPS

> D5 定案：12 個月內**不開**公開自助註冊。

---

## 1. 開戶前檢查清單

- [ ] 合約／Design Partner 書面或等價確認  
- [ ] 方案選定：`pilot`／`team`／`business`／`enterprise`  
- [ ] 資料駐留區域（Phase 1 單區）確認  
- [ ] DPA 草稿已送法務（`docs/legal/DPA_TEMPLATE.md`）  
- [ ] 客戶技術聯絡人、owner email

---

## 2. 形態 B：拉起實例

```bash
python scripts/provision_managed_instance.py --customer <slug> --plan team --write-env
# 將 artifacts/ops/<slug>.env.production 部署至 VM，填入 S3／LLM／NewebPay
# 依 docs/runbooks/MANAGED_PRIVATE_CLOUD.md 執行 Compose up + migrate
```

煙霧：

```bash
export ENCLAVE_URL=https://<customer-domain>
export POC_OWNER_EMAIL=...
export POC_OWNER_PASSWORD=...
python scripts/managed_poc_smoke.py
python scripts/cloud_release_gate.py --strict
```

人類閘門：

```bash
python scripts/provision_managed_instance.py --customer <slug> --confirm-delivery
```

---

## 3. 租戶與 Owner

1. Superuser 建立租戶（方案矩陣見 `PLAN_QUOTAS`）。  
2. 建立 owner；`MFA_ENFORCE_OWNER=true` 時強制 TOTP。  
3. Business+：設定 SSO（`redirect_uri` **必須**與 IdP 登記值一致）。  
4. 邀請使用者 ≤ 方案人數上限。  
5. 首批上傳 + 客製盲測 10 題（Sales-Led 清單）。

---

## 4. 付款與升等（CG-PAY）

```bash
# 模擬閉環（無商戶憑證）
python scripts/e2e_payment_newebpay.py

# 生產：Owner 呼叫 POST /api/v1/payment/checkout → 藍新 MPG → /payment/notify
```

未設 `NEWEBPAY_MERCHANT_ID` 時 checkout 回 **503**（fail-closed）。

---

## 5. Day 0／1／3

| 日 | 動作 |
|----|------|
| 0 | 交付確認、owner MFA、首份文件上傳 |
| 1 | 驗收題通過、用量儀表可讀 |
| 3 | 支援回訪；記錄問題至事件／ticket |

---

## 6. 相關文件

- `docs/runbooks/MANAGED_PRIVATE_CLOUD.md`  
- `docs/runbooks/DATA_DELETION_AND_EXPORT.md`  
- `docs/legal/DPA_TEMPLATE.md`  
- `docs/OPEN_GATES.md`
