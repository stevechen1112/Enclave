# ADR-001：Sidecar/Adapter 為預設整合模式

**狀態**：已接受
**日期**：2026-07-31
**決策者**：Enclave 技術團隊

---

## 背景

Enclave 需要整合 RAGFlow（文件解析）、PipesHub（連接器與權限感知）、WeKnora（知識編譯與 GraphRAG）三者的核心能力。有兩種整合模式可選：

- **模式 A**：Fork/移植 — 將上游程式碼抽取後直接嵌入 Enclave 程式庫
- **模式 B**：Sidecar/Adapter — 上游以獨立容器執行，Enclave 透過版本化 HTTP/gRPC 契約呼叫

## 決策

**採用模式 B：Containerized Sidecar/Data Plane + Enclave Adapter。**

## 理由

1. **上游演進獨立**：RAGFlow（~86k stars）、WeKnora（~19k stars）、PipesHub 都在快速迭代。Fork 後追蹤上游變更的成本遠高於維護 Adapter 契約。
2. **技術棧隔離**：RAGFlow 是 Python+Go、WeKnora 是 Go、PipesHub 是 Node.js+Python。嵌入 Enclave（Python/FastAPI）會引入三套異質 runtime 的建置與維運負擔。
3. **故障隔離**：Sidecar 模式讓下游故障不影響 Enclave 核心（身分、授權、稽核）的可用性。
4. **可替換性**：若日後某個上游停止維護或授權變更，只需更換 Adapter 實作，不影響 Enclave 公開 API。
5. **授權合規**：不修改上游原始碼（僅透過公開 API 呼叫），簡化 Apache 2.0/MIT 的 NOTICE 義務。

## 約束

- 使用固定版本與映像 digest 的容器，不追 `latest` tag。
- 禁止 Enclave 直接讀寫下游資料庫。
- 下游端口只在內部 Docker network 暴露。
- MCP 用於 Agent 工具發現與執行，不用於大量文件二進位傳輸。
- 若日後需內化某項能力，必須有獨立 ADR、相容性測試與遷移計畫。

## 後果

- 需要維護 Adapter 契約的版本相容性。
- 部署複雜度略高於單體（多個容器）。
- 跨服務呼叫有網路延遲，需設計 timeout/retry/circuit breaker。
