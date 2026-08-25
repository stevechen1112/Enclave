# Corpus 與評測用途凍結

| 資料集 | 用途 | 是否可讀取修程式 | 結果規則 |
|---|---|---:|---|
| 主集、對抗集 | regression | 是 | 不得冒充盲測 |
| Blind Z3／Z4 | frozen historical baseline | 是（已開封） | 首次分數不可覆蓋 |
| Blind Z5 | sealed holdout until first K0 run | 否 | 首跑後永久轉 regression |
| debug／neighbor | diagnostic/regression | 是 | 不計入泛化宣稱 |
| production shadow | tenant acceptance | 僅唯讀 | 不計入平台 sealed holdout |

正式與測試資料以 tenant ID、KB ID、revision ID 三層隔離。Artifact 僅保存計數、stable ID digest、題庫 hash 與結果，不保存正式文件原文、使用者 email、ACL subject ID 或 token。

