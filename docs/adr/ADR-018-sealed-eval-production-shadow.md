# ADR-018：跨領域盲測與正式 Shadow

- 狀態：Accepted
- 日期：2026-08-25

## 決策

題庫、語料、GT 與 scoring 在執行前 hash 封存。每個 evaluation key 的首次結果以資料庫 partial unique constraint 固定，後續只能新增 repeat 並指向 baseline，不得覆寫首跑。

報告分列 PASS、FAIL、BLOCKED、SKIPPED、REVIEW；比率公布分子、分母、領域／題型分布與 Wilson 95% 區間。正式 Shadow 以資料庫 read-only barrier 執行，綁定 image digest、KB revision 與 manifest；每題須有最少結果或預期文件契約，空結果不得算 PASS。

## 後果

開封題庫永久轉 regression。平台 GO 需要兩個語料不重疊的新 sealed holdout，不能以反覆修過的 corpus 代替。
