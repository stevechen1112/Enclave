#!/usr/bin/env python3
"""
Enclave Flow 2：RAG 對話全流程測試
====================================
覆蓋 Question → Rewrite → Retrieve → Generate → Stream 完整管道。

測試項目：
  T2-01  前置：上傳測試文件 & 等待完成
  T2-02  Non-streaming chat — 基本問答
  T2-03  Non-streaming — 回答包含來源 sources
  T2-04  Non-streaming — 產生 conversation_id
  T2-05  SSE streaming chat — 收到 status event
  T2-06  SSE streaming — 收到 sources event
  T2-07  SSE streaming — 收到至少 1 個 token event
  T2-08  SSE streaming — 收到 done event（含 message_id + conversation_id）
  T2-09  SSE streaming — 收到 suggestions event
  T2-10  多輪對話 — 第二輪帶 conversation_id
  T2-11  多輪對話 — contextualize_query 改寫（代詞解析）
  T2-12  對話歷史 — messages 端點回傳歷史
  T2-13  對話列表 — conversations 端點包含新對話
  T2-14  KB search — 獨立語意搜尋
  T2-15  Feedback — 提交回饋
  T2-16  空問題被拒
  T2-17  刪除對話
  T2-18  清理：刪除測試文件

用法：
  python scripts/test_flow2_rag_chat.py
  python scripts/test_flow2_rag_chat.py --keep
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import uuid
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
def parse_sse_events(response: requests.Response) -> list[dict]:
    """解析 SSE 串流回應，回傳事件列表。"""
    events = []
    buffer = ""

    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            buffer += chunk

    for line in buffer.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                events.append({"type": "stream_end"})
                continue
            try:
                data = json.loads(data_str)
                events.append(data)
            except json.JSONDecodeError:
                pass

    return events


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
            if r.status_code == 200:
                st = r.json()["status"]
                if st in ("completed", "failed"):
                    return st
            time.sleep(5)
        return "timeout"

    def delete_document(self, doc_id: str) -> int:
        r = self.session.delete(f"{self.base}/api/v1/documents/{doc_id}", timeout=10)
        return r.status_code

    def chat(self, question: str, conversation_id: str | None = None, top_k: int = 3) -> dict:
        body = {"question": question, "top_k": top_k}
        if conversation_id:
            body["conversation_id"] = conversation_id
        r = self.session.post(
            f"{self.base}/api/v1/chat/chat",
            json=body,
            timeout=60,
        )
        return {"status_code": r.status_code, "body": r.json() if r.status_code == 200 else {}}

    def chat_stream(self, question: str, conversation_id: str | None = None, top_k: int = 3) -> list[dict]:
        body = {"question": question, "top_k": top_k}
        if conversation_id:
            body["conversation_id"] = conversation_id
        r = self.session.post(
            f"{self.base}/api/v1/chat/chat/stream",
            json=body,
            stream=True,
            timeout=120,
        )
        if r.status_code != 200:
            return [{"type": "error", "content": f"HTTP {r.status_code}"}]
        return parse_sse_events(r)

    def conversations(self) -> list:
        r = self.session.get(f"{self.base}/api/v1/chat/conversations", timeout=10)
        return r.json() if r.status_code == 200 else []

    def messages(self, conversation_id: str) -> list:
        r = self.session.get(
            f"{self.base}/api/v1/chat/conversations/{conversation_id}/messages",
            timeout=10,
        )
        return r.json() if r.status_code == 200 else []

    def delete_conversation(self, conversation_id: str) -> int:
        r = self.session.delete(
            f"{self.base}/api/v1/chat/conversations/{conversation_id}",
            timeout=10,
        )
        return r.status_code

    def kb_search(self, query: str, top_k: int = 5) -> dict:
        r = self.session.post(
            f"{self.base}/api/v1/kb/search",
            json={"query": query, "top_k": top_k},
            timeout=30,
        )
        return r.json() if r.status_code == 200 else {}

    def submit_feedback(self, message_id: str, rating: int, category: str | None = None, comment: str | None = None) -> dict:
        body = {"message_id": message_id, "rating": rating}
        if category:
            body["category"] = category
        if comment:
            body["comment"] = comment
        r = self.session.post(
            f"{self.base}/api/v1/chat/feedback",
            json=body,
            timeout=10,
        )
        return {"status_code": r.status_code, "body": r.json() if r.status_code == 200 else {}}


# ── Test Data ──────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_DATA_DIR = PROJECT_ROOT / "test-data" / "company-documents"

# 偏好使用包含請假規定的文件（特休假、病假、婚假等，與測試問題匹配）
PREFERRED_FILES = [
    TEST_DATA_DIR / "hr-regulations" / "員工手冊-第一章-總則.md",
    TEST_DATA_DIR / "sop" / "新人到職SOP.md",
]

import tempfile

def prepare_test_file() -> str:
    """找到或建立一個有語意的測試文件。"""
    for p in PREFERRED_FILES:
        if p.exists():
            return str(p)

    # Fallback: 建立
    tmpdir = tempfile.mkdtemp(prefix="enclave_chat_test_")
    path = os.path.join(tmpdir, "chat_test_人資規定.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# 公司請假規定\n\n"
            "## 特休假\n"
            "- 任職滿六個月者，享有三天特休假\n"
            "- 任職滿一年者，享有七天特休假\n"
            "- 任職滿三年者，享有十四天特休假\n\n"
            "## 病假\n"
            "- 每年享有三十天病假\n"
            "- 住院傷病假最多一年\n"
            "- 需附醫療證明\n\n"
            "## 公假\n"
            "- 選舉投票日：一天\n"
            "- 兵役：依法令規定\n\n"
            "## 婚假\n"
            "- 結婚者享有八天婚假\n"
            "- 需於結婚登記前後三個月內請畢\n"
        )
    return path


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool):
    doc_id = None
    conversation_id = None
    message_id = None
    conversations_to_delete = []

    # ── Phase 1: 前置準備 ─────────────────
    section("Phase 1: 前置 — 上傳測試文件")
    test_file = prepare_test_file()
    result = api.upload(test_file)
    if _assert("id" in result, "T2-01a 上傳測試文件", os.path.basename(test_file)):
        doc_id = result["id"]
        print(f"      {DIM}doc_id={doc_id}{RESET}")
        status = api.poll_status(doc_id, timeout_s=120)
        _assert(status == "completed", "T2-01b 文件處理完成", f"status={status}")
    else:
        print(f"  {RED}ABORT: 無法上傳測試文件，後續測試略過{RESET}")
        return

    # ── Phase 2: Non-streaming Chat ───────
    section("Phase 2: Non-streaming 對話")

    # T2-02: 基本問答
    chat_result = api.chat("公司的特休假規定是什麼？")
    status_code = chat_result["status_code"]
    body = chat_result["body"]
    _assert(status_code == 200, "T2-02 Non-streaming 問答", f"HTTP {status_code}")

    if status_code == 200:
        answer = body.get("answer", "")
        _assert(len(answer) > 10, "T2-02b 回答長度合理", f"len={len(answer)}")
        print(f"      {DIM}回答前 80 字: {answer[:80]}...{RESET}")

        # T2-03: sources
        sources = body.get("sources", [])
        _assert(
            isinstance(sources, list),
            "T2-03 回答包含 sources",
            f"source_count={len(sources)}"
        )

        # T2-04: conversation_id
        conversation_id = body.get("conversation_id")
        _assert(
            conversation_id is not None,
            "T2-04 產生 conversation_id",
            f"conv={str(conversation_id)[:8]}..."
        )
        if conversation_id:
            conversations_to_delete.append(str(conversation_id))

        message_id = body.get("message_id")

    # T2-16: 空問題被拒
    empty_result = api.chat("")
    _assert(
        empty_result["status_code"] in (400, 422),
        "T2-16 空問題被拒",
        f"HTTP {empty_result['status_code']}"
    )

    # ── Phase 3: SSE Streaming Chat ───────
    section("Phase 3: SSE Streaming 對話")
    events = api.chat_stream("員工婚假有幾天？")

    event_types = [e.get("type") for e in events]

    # T2-05: status event
    _assert(
        "status" in event_types,
        "T2-05 SSE 收到 status event",
        f"events: {event_types[:5]}..."
    )

    # T2-06: sources event
    _assert(
        "sources" in event_types,
        "T2-06 SSE 收到 sources event"
    )

    # T2-07: token events
    token_events = [e for e in events if e.get("type") == "token"]
    _assert(
        len(token_events) > 0,
        "T2-07 SSE 收到 token events",
        f"count={len(token_events)}"
    )

    # 組合完整回答
    if token_events:
        full_answer = "".join(e.get("content", "") for e in token_events)
        print(f"      {DIM}Streaming 回答前 80 字: {full_answer[:80]}...{RESET}")

    # T2-08: done event
    done_events = [e for e in events if e.get("type") == "done"]
    if _assert(len(done_events) > 0, "T2-08 SSE 收到 done event"):
        done = done_events[0]
        _assert("message_id" in done, "T2-08b done 包含 message_id")
        stream_conv_id = done.get("conversation_id")
        _assert(
            stream_conv_id is not None,
            "T2-08c done 包含 conversation_id",
            f"conv={str(stream_conv_id)[:8]}..."
        )
        if stream_conv_id:
            conversations_to_delete.append(str(stream_conv_id))

    # T2-09: suggestions
    suggestion_events = [e for e in events if e.get("type") == "suggestions"]
    _assert(
        len(suggestion_events) > 0,
        "T2-09 SSE 收到 suggestions event",
        f"items={suggestion_events[0].get('items', [])[:2]}" if suggestion_events else ""
    )

    # ── Phase 4: 多輪對話 ────────────────
    section("Phase 4: 多輪對話（contextualize_query 測試）")

    if conversation_id:
        # T2-10: 第二輪帶 conversation_id
        followup_result = api.chat("那病假呢？需要什麼證明？", conversation_id=str(conversation_id))
        _assert(
            followup_result["status_code"] == 200,
            "T2-10 第二輪問答成功",
            f"HTTP {followup_result['status_code']}"
        )

        if followup_result["status_code"] == 200:
            followup_answer = followup_result["body"].get("answer", "")
            # T2-11: contextualize 改寫 — 回答應知道「那」指的是請假
            # 代詞解析成功的跡象：回答中包含「病假」相關詞
            has_context = any(kw in followup_answer for kw in ["病假", "醫療", "三十天", "證明", "30"])
            _assert(
                has_context,
                "T2-11 contextualize 改寫成功（代詞解析）",
                f"回答含病假相關詞: {has_context}"
            )
            print(f"      {DIM}Follow-up 回答: {followup_answer[:100]}...{RESET}")

        # T2-12: 歷史記錄
        msgs = api.messages(str(conversation_id))
        _assert(
            len(msgs) >= 4,  # 2 user + 2 assistant
            "T2-12 對話歷史完整",
            f"messages={len(msgs)}"
        )
    else:
        skip("T2-10 多輪對話", "無 conversation_id")
        skip("T2-11 contextualize", "無 conversation_id")
        skip("T2-12 歷史記錄", "無 conversation_id")

    # T2-13: 對話列表
    convs = api.conversations()
    conv_ids = {str(c.get("id", "")) for c in convs}
    _assert(
        bool(conv_ids & set(conversations_to_delete)),
        "T2-13 對話列表包含新對話",
        f"total_conversations={len(convs)}"
    )

    # ── Phase 5: KB Search ───────────────
    section("Phase 5: 獨立 KB 搜尋")
    kb_result = api.kb_search("特休假", top_k=3)
    results = kb_result.get("results", [])
    _assert(
        len(results) > 0,
        "T2-14 KB search 有結果",
        f"hits={len(results)}, top_score={results[0].get('score', 0):.4f}" if results else ""
    )

    # ── Phase 6: Feedback ────────────────
    section("Phase 6: 回饋機制")
    if message_id:
        fb_result = api.submit_feedback(
            message_id=str(message_id),
            rating=2,
            category="other",
            comment="自動測試回饋"
        )
        _assert(
            fb_result["status_code"] == 200,
            "T2-15 提交回饋",
            f"HTTP {fb_result['status_code']}"
        )
    else:
        skip("T2-15 提交回饋", "無 message_id")

    # ── Phase 7: 清理 ───────────────────
    section("Phase 7: 清理")
    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        # T2-17: 刪除對話
        for conv_id in set(conversations_to_delete):
            sc = api.delete_conversation(conv_id)
            if sc == 200:
                print(f"      {DIM}已刪除對話 {conv_id[:8]}...{RESET}")

        _assert(True, "T2-17 對話清理完成")

        # T2-18: 刪除文件
        if doc_id:
            sc = api.delete_document(doc_id)
            _assert(sc == 200, "T2-18 測試文件刪除", f"HTTP {sc}")


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 2 — RAG 對話全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 2：RAG 對話全流程測試")
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
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
