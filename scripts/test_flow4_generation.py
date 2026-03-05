#!/usr/bin/env python3
"""
Enclave Flow 4：內容生成全流程測試
====================================
覆蓋 Template → KB Retrieval → LLM Stream → Export 管道。

測試項目：
  T4-01  前置：上傳測試文件 & 等待完成
  T4-02  模板列表端點可達
  T4-03  模板列表包含 5 種範本
  T4-04  SSE 串流生成 — draft_response
  T4-05  SSE 串流 — 收到至少 1 個 content chunk
  T4-06  SSE 串流 — 收到 [DONE] 結束標記
  T4-07  SSE 串流 — case_summary 模板
  T4-08  SSE 串流 — meeting_minutes 模板
  T4-09  SSE 串流 — analysis_report 模板
  T4-10  SSE 串流 — faq_draft 模板
  T4-11  帶 context_query 的 RAG 增強生成
  T4-12  帶 document_ids 的指定文件生成
  T4-13  匯出 DOCX
  T4-14  匯出 PDF
  T4-15  空提示被拒
  T4-16  無效模板被拒
  T4-17  清理：刪除測試文件

用法：
  python scripts/test_flow4_generation.py
  python scripts/test_flow4_generation.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests

# Windows cp950 workaround: force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── UI ─────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def ok(name: str, detail: str = "") -> None:
    global passed
    passed += 1
    msg = f"  {GREEN}✔ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def fail(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  {RED}✘ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def skip(name: str, reason: str = "") -> None:
    global skipped
    skipped += 1
    print(f"  {YELLOW}⊘ {name} — SKIP: {reason}{RESET}")


def section(title: str):
    print(f"\n{BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{RESET}")


def _assert(condition: bool, name: str, detail: str = "") -> bool:
    if condition:
        ok(name, detail)
    else:
        fail(name, detail)
    return condition


# ── SSE Parser ─────────────────────────────────
def parse_sse_generate(response: requests.Response) -> dict:
    """解析 generate/stream 的 SSE 回應。"""
    chunks: list[str] = []
    errors: list[str] = []
    got_done = False

    buffer = ""
    for raw_chunk in response.iter_content(chunk_size=None, decode_unicode=True):
        if raw_chunk:
            buffer += raw_chunk

    for line in buffer.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                got_done = True
                continue
            try:
                data = json.loads(data_str)
                if "content" in data:
                    chunks.append(data["content"])
                if "error" in data:
                    errors.append(data["error"])
            except json.JSONDecodeError:
                pass

    return {
        "chunks": chunks,
        "full_text": "".join(chunks),
        "got_done": got_done,
        "errors": errors,
    }


# ── API Client ─────────────────────────────────
class ApiClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url
        self.session = requests.Session()
        r = self.session.post(
            f"{self.base}/api/v1/auth/login/access-token",
            data={"username": user, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def upload(self, filepath: str) -> dict:
        with open(filepath, "rb") as fh:
            r = self.session.post(
                f"{self.base}/api/v1/documents/upload",
                files={"file": (os.path.basename(filepath), fh)},
                timeout=30,
            )
        return r.json() if r.status_code == 200 else {}

    def poll_status(self, doc_id: str, timeout_s: int = 120) -> str:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r = self.session.get(f"{self.base}/api/v1/documents/{doc_id}", timeout=10)
            if r.status_code == 200 and r.json()["status"] in ("completed", "failed"):
                return r.json()["status"]
            time.sleep(5)
        return "timeout"

    def delete_document(self, doc_id: str) -> int:
        r = self.session.delete(f"{self.base}/api/v1/documents/{doc_id}", timeout=10)
        return r.status_code

    def get_templates(self) -> dict:
        r = self.session.get(f"{self.base}/api/v1/generate/templates", timeout=10)
        return {"status_code": r.status_code, "body": r.json() if r.status_code == 200 else {}}

    def generate_stream(
        self,
        template: str,
        user_prompt: str,
        context_query: str = "",
        max_tokens: int = 1000,
        document_ids: list[str] | None = None,
    ) -> dict:
        body = {
            "template": template,
            "user_prompt": user_prompt,
            "context_query": context_query,
            "max_tokens": max_tokens,
        }
        if document_ids:
            body["document_ids"] = document_ids
        r = self.session.post(
            f"{self.base}/api/v1/generate/stream",
            json=body,
            stream=True,
            timeout=120,
        )
        if r.status_code != 200:
            return {
                "chunks": [],
                "full_text": "",
                "got_done": False,
                "errors": [f"HTTP {r.status_code}"],
                "status_code": r.status_code,
            }
        result = parse_sse_generate(r)
        result["status_code"] = 200
        return result

    def export_docx(self, content: str, title: str = "測試文件") -> requests.Response:
        return self.session.post(
            f"{self.base}/api/v1/generate/export/docx",
            json={"content": content, "title": title, "sources": [], "template": None},
            timeout=30,
        )

    def export_pdf(self, content: str, title: str = "測試文件") -> requests.Response:
        return self.session.post(
            f"{self.base}/api/v1/generate/export/pdf",
            json={"content": content, "title": title, "sources": [], "template": None},
            timeout=30,
        )


# ── Results Directory ──────────────────────────
def create_results_dir() -> Path:
    """建立帶時間戳的結果目錄，用於存檔生成內容備查。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).resolve().parent.parent / "test-results" / f"flow4_generation_{ts}"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


# ── Test Data ──────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_DATA_DIR = PROJECT_ROOT / "test-data" / "company-documents"

# 偏好使用與差旅報帳相關的文件（與測試 prompt 匹配）
PREFERRED_FILES = [
    TEST_DATA_DIR / "sop" / "報帳作業規範.md",
    TEST_DATA_DIR / "sop" / "新人到職SOP.md",
    TEST_DATA_DIR / "hr-regulations" / "員工手冊-第一章-總則.md",
]


def prepare_test_file() -> str:
    for p in PREFERRED_FILES:
        if p.exists():
            return str(p)

    tmpdir = tempfile.mkdtemp(prefix="enclave_gen_test_")
    path = os.path.join(tmpdir, "gen_test_公司規定.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# 公司差旅報帳辦法\n\n"
            "## 報帳原則\n"
            "1. 出差前需填寫差旅申請單\n"
            "2. 返回後五日內完成報帳\n"
            "3. 檢附原始憑證\n\n"
            "## 交通費\n"
            "- 高鐵：商務車廂（經理級以上）\n"
            "- 計程車：需註明起訖地址\n\n"
            "## 住宿費\n"
            "- 國內出差每晚上限 3,000 元\n"
            "- 海外出差依地區調整\n\n"
            "## 膳雜費\n"
            "- 國內每日 500 元\n"
            "- 海外依地區外交部標準\n"
        )
    return path


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
EXPECTED_TEMPLATES = ["draft_response", "case_summary", "meeting_minutes", "analysis_report", "faq_draft"]


def run_tests(api: ApiClient, keep: bool):
    doc_id = None
    generated_content = ""
    results_dir = create_results_dir()
    print(f"  {DIM}生成內容儲存目錄: {results_dir}{RESET}")

    # ── Phase 1: 前置 ───────────────────
    section("Phase 1: 前置 — 上傳知識庫文件")
    test_file = prepare_test_file()
    result = api.upload(test_file)
    if _assert("id" in result, "T4-01a 上傳測試文件", os.path.basename(test_file)):
        doc_id = result["id"]
        status = api.poll_status(doc_id)
        _assert(status == "completed", "T4-01b 文件處理完成", f"status={status}")
    else:
        print(f"  {RED}ABORT: 無法上傳，後續測試可能無 RAG 語境{RESET}")

    # ── Phase 2: 模板列表 ────────────────
    section("Phase 2: 模板列表")
    tmpl_result = api.get_templates()
    _assert(
        tmpl_result["status_code"] == 200,
        "T4-02 模板列表端點可達",
        f"HTTP {tmpl_result['status_code']}"
    )

    if tmpl_result["status_code"] == 200:
        templates = tmpl_result["body"].get("templates", [])
        tmpl_ids = [t.get("id") for t in templates]
        _assert(
            len(templates) >= 5,
            "T4-03 模板列表包含 5 種範本",
            f"got={tmpl_ids}"
        )
        for t in templates:
            print(f"      {DIM}{t.get('id')}: {t.get('name')}{RESET}")

    # ── Phase 3: 各模板串流生成 ──────────
    section("Phase 3: SSE 串流生成（5 種模板）")

    template_prompts = {
        "draft_response": ("T4-04", "請代擬一份關於差旅報帳流程說明的函件", "差旅報帳"),
        "case_summary": ("T4-07", "請摘要公司出差相關規定的重點", "出差規定"),
        "meeting_minutes": ("T4-08", "請整理成會議記錄格式：討論了差旅報帳新政策", "差旅新政策"),
        "analysis_report": ("T4-09", "請分析現行差旅報帳辦法的優缺點", "報帳辦法分析"),
        "faq_draft": ("T4-10", "請針對差旅報帳製作常見問答集", "差旅報帳 FAQ"),
    }

    first_generated = None
    for template, (test_id, prompt, ctx_query) in template_prompts.items():
        result = api.generate_stream(
            template=template,
            user_prompt=prompt,
            context_query=ctx_query,
            max_tokens=500,
        )

        has_chunks = len(result["chunks"]) > 0
        _assert(
            has_chunks,
            f"{test_id} {template} 生成有 chunk",
            f"chunks={len(result['chunks'])}, len={len(result['full_text'])}"
        )

        if has_chunks and first_generated is None:
            first_generated = result["full_text"]
            generated_content = result["full_text"]

        if result.get("errors"):
            fail(f"{test_id} {template} 有 error", str(result["errors"][:1]))

        if has_chunks:
            print(f"      {DIM}前 60 字: {result['full_text'][:60]}...{RESET}")

        # ── 存檔備查 ──
        save_path = results_dir / f"{test_id}_{template}.md"
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"# {test_id} — {template}\n\n")
            f.write(f"**Prompt**: {prompt}\n\n")
            f.write(f"**Context Query**: {ctx_query}\n\n")
            f.write(f"**Chunks**: {len(result['chunks'])}\n\n")
            f.write(f"**Got Done**: {result['got_done']}\n\n")
            if result.get('errors'):
                f.write(f"**Errors**: {result['errors']}\n\n")
            f.write("---\n\n")
            f.write(result["full_text"] if result["full_text"] else "(no content)")
        print(f"      {DIM}已存檔: {save_path.name}{RESET}")

    # T4-05 & T4-06: 驗證第一個生成結果的結構
    if first_generated:
        _assert(len(first_generated) > 20, "T4-05 生成內容長度合理", f"len={len(first_generated)}")

    # 重新做一次 draft_response 確認 [DONE]
    result2 = api.generate_stream(
        template="draft_response",
        user_prompt="簡短回覆，一句話即可",
        max_tokens=100,
    )
    _assert(result2["got_done"], "T4-06 SSE 收到 [DONE] 結束標記")

    # ── Phase 4: RAG 增強 & 指定文件 ────
    section("Phase 4: RAG 增強生成")

    # T4-11: 帶 context_query
    result = api.generate_stream(
        template="analysis_report",
        user_prompt="分析公司新人到職流程的效率",
        context_query="新人到職流程",
        max_tokens=500,
    )
    has_rag_content = len(result["chunks"]) > 0
    _assert(
        has_rag_content,
        "T4-11 帶 context_query 的 RAG 生成",
        f"chunks={len(result['chunks'])}"
    )
    # 存檔
    save_path = results_dir / "T4-11_rag_analysis_report.md"
    with open(save_path, "w", encoding="utf-8") as f:
        f.write("# T4-11 — RAG 增強 analysis_report\n\n")
        f.write("**Prompt**: 分析公司新人到職流程的效率\n\n")
        f.write("---\n\n")
        f.write(result["full_text"] if result["full_text"] else "(no content)")
    print(f"      {DIM}已存檔: {save_path.name}{RESET}")

    # T4-12: 帶 document_ids
    if doc_id:
        result = api.generate_stream(
            template="case_summary",
            user_prompt="摘要這份文件的重點",
            document_ids=[doc_id],
            max_tokens=500,
        )
        _assert(
            len(result["chunks"]) > 0,
            "T4-12 帶 document_ids 的指定文件生成",
            f"chunks={len(result['chunks'])}"
        )
        # 存檔
        save_path = results_dir / "T4-12_doc_specific_summary.md"
        with open(save_path, "w", encoding="utf-8") as f:
            f.write("# T4-12 — 指定文件 case_summary\n\n")
            f.write(f"**Document ID**: {doc_id}\n\n")
            f.write("---\n\n")
            f.write(result["full_text"] if result["full_text"] else "(no content)")
        print(f"      {DIM}已存檔: {save_path.name}{RESET}")
    else:
        skip("T4-12 指定文件生成", "無 doc_id")

    # ── Phase 5: 匯出 ───────────────────
    section("Phase 5: 匯出（DOCX / PDF）")

    export_content = generated_content or "# 測試匯出\n\n這是自動測試產生的內容。\n\n## 重點\n- 項目一\n- 項目二"

    # T4-13: DOCX
    r = api.export_docx(export_content, title="Flow4_測試匯出")
    if _assert(r.status_code == 200, "T4-13 匯出 DOCX", f"HTTP {r.status_code}"):
        content_type = r.headers.get("Content-Type", "")
        _assert(
            "officedocument" in content_type or "octet-stream" in content_type,
            "T4-13b DOCX Content-Type 正確",
            content_type[:60]
        )
        _assert(len(r.content) > 100, "T4-13c DOCX 大小合理", f"{len(r.content)} bytes")
        # 存檔 DOCX
        docx_path = results_dir / "T4-13_export.docx"
        docx_path.write_bytes(r.content)
        print(f"      {DIM}已存檔: {docx_path.name} ({len(r.content)} bytes){RESET}")

    # T4-14: PDF
    r = api.export_pdf(export_content, title="Flow4_測試匯出")
    if _assert(r.status_code == 200, "T4-14 匯出 PDF", f"HTTP {r.status_code}"):
        content_type = r.headers.get("Content-Type", "")
        _assert(
            "pdf" in content_type or "octet-stream" in content_type,
            "T4-14b PDF Content-Type 正確",
            content_type[:60]
        )
        _assert(len(r.content) > 100, "T4-14c PDF 大小合理", f"{len(r.content)} bytes")
        # 驗證 PDF magic bytes
        if r.content[:4] == b"%PDF":
            ok("T4-14d PDF magic bytes 正確")
        else:
            fail("T4-14d PDF magic bytes 不正確", f"got: {r.content[:10]}")
        # 存檔 PDF
        pdf_path = results_dir / "T4-14_export.pdf"
        pdf_path.write_bytes(r.content)
        print(f"      {DIM}已存檔: {pdf_path.name} ({len(r.content)} bytes){RESET}")

    # ── Phase 6: 邊界條件 ────────────────
    section("Phase 6: 邊界條件")

    # T4-15: 空提示
    result = api.generate_stream(
        template="draft_response",
        user_prompt="",
        max_tokens=100,
    )
    # 可能回傳 error 或 422
    is_rejected = result.get("status_code") in (400, 422) or bool(result.get("errors"))
    _assert(
        is_rejected or len(result["chunks"]) == 0,
        "T4-15 空提示被拒或無輸出",
        f"status={result.get('status_code')}, errors={result.get('errors', [])}"
    )

    # T4-16: 無效模板
    result = api.generate_stream(
        template="nonexistent_template",
        user_prompt="測試",
        max_tokens=100,
    )
    _assert(
        result.get("status_code") in (400, 422) or bool(result.get("errors")),
        "T4-16 無效模板被拒",
        f"status={result.get('status_code')}"
    )

    # ── Phase 7: 清理 ───────────────────
    section("Phase 7: 清理")
    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        if doc_id:
            sc = api.delete_document(doc_id)
            _assert(sc == 200, "T4-17 測試文件刪除", f"HTTP {sc}")


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 4 — 內容生成全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 4：內容生成全流程測試")
    print(f"  Target: {args.base_url}")
    print(f"═══════════════════════════════════════════════════{RESET}")

    try:
        api = ApiClient(args.base_url, args.user, args.password)
        ok("登入成功")
    except Exception as e:
        fail(f"登入失敗: {e}")
        sys.exit(1)

    run_tests(api, keep=args.keep)

    section("結果摘要")
    total = passed + failed + skipped
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}跳過: {skipped}{RESET}  總計: {total}")

    # 產出摘要索引檔
    results_dirs = sorted((Path(__file__).resolve().parent.parent / "test-results").glob("flow4_generation_*"))
    if results_dirs:
        latest = results_dirs[-1]
        idx_path = latest / "_INDEX.md"
        saved_files = sorted(f.name for f in latest.iterdir() if f.name != "_INDEX.md")
        with open(idx_path, "w", encoding="utf-8") as f:
            f.write(f"# Flow 4 生成結果備查\n\n")
            f.write(f"**執行時間**: {latest.name.replace('flow4_generation_', '')}\n\n")
            f.write(f"**結果**: 通過={passed}, 失敗={failed}, 跳過={skipped}\n\n")
            f.write(f"## 存檔清單\n\n")
            for sf in saved_files:
                f.write(f"- [{sf}]({sf})\n")
        print(f"\n  {DIM}📁 所有生成內容已存檔至: {latest}{RESET}")
        print(f"  {DIM}📋 索引檔: {idx_path}{RESET}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
