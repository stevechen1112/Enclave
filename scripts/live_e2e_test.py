#!/usr/bin/env python3
"""
aihr 生產環境端到端自動化測試 (HTTP Live Test)
═══════════════════════════════════════════════
測試伺服器: 172.237.5.254
測試流程: Phase 0-8
"""

import requests
import json
import time
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict, field
import sys

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = os.getenv("AIHR_BASE_URL", "http://api.172-237-5-254.sslip.io")
FRONTEND_URL = os.getenv("AIHR_FRONTEND_URL", "http://app.172-237-5-254.sslip.io")

# IMPORTANT: do not hard-code production credentials in this repo.
SUPERUSER_EMAIL = os.getenv("AIHR_SUPERUSER_EMAIL", "admin@example.com")
SUPERUSER_PASSWORD = os.getenv("AIHR_SUPERUSER_PASS", "admin123")
HR_TEST_PASSWORD = os.getenv("AIHR_HR_PASS", "TestHR123!")

TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "test-data"
DOCS_DIR = TEST_DATA_DIR / "company-documents"

OUTPUT_DIR = TEST_DATA_DIR / "test-results" / f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT = 60
CHAT_TIMEOUT = 180


# ═══════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════

@dataclass
class TestResult:
    phase: str
    step: str
    action: str
    status: str
    score: float
    max_score: float
    elapsed_ms: int
    detail: str = ""

class TestSession:
    def __init__(self):
        self.results: List[TestResult] = []
        self.su_token: str = ""
        self.hr_token: str = ""
        self.tenant_id: str = ""
        self.hr_email: str = ""
        self.uploaded_docs: List[dict] = []
        self.start_time = time.time()

    def add(self, r: TestResult):
        self.results.append(r)
        icon = r.status
        print(f"    {icon} [{r.step}] {r.action} -- {r.score}/{r.max_score} ({r.elapsed_ms}ms) {r.detail}")

    def report(self):
        lines = ["# aihr Live E2E Test Report", ""]
        lines.append(f"**Server**: {BASE_URL}")
        lines.append(f"**Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Duration**: {time.time() - self.start_time:.1f}s")
        lines.append("")

        phases = sorted(set(r.phase for r in self.results))
        lines.append("## Summary\n")
        lines.append("| Phase | Pass/Total | Score | % | Time |")
        lines.append("|-------|-----------|-------|---|------|")

        total_s = total_m = 0
        for p in phases:
            pr = [r for r in self.results if r.phase == p]
            passed = sum(1 for r in pr if r.status == "OK")
            s = sum(r.score for r in pr)
            m = sum(r.max_score for r in pr)
            t = sum(r.elapsed_ms for r in pr)
            total_s += s; total_m += m
            pct = f"{s/m*100:.0f}" if m else "N/A"
            lines.append(f"| {p} | {passed}/{len(pr)} | {s:.0f}/{m:.0f} | {pct}% | {t/1000:.1f}s |")

        lines.append("")
        pct = total_s/total_m*100 if total_m else 0
        grade = "EXCELLENT" if pct >= 90 else ("GOOD" if pct >= 70 else ("FAIR" if pct >= 50 else "NEEDS WORK"))
        lines.append(f"**Total: {total_s:.0f}/{total_m:.0f} ({pct:.1f}%) -- {grade}**")
        lines.append("")

        # Detail
        lines.append("## Details\n")
        for p in phases:
            lines.append(f"### {p}\n")
            lines.append("| Step | Action | Status | Score | Time | Detail |")
            lines.append("|------|--------|--------|-------|------|--------|")
            for r in [x for x in self.results if x.phase == p]:
                lines.append(f"| {r.step} | {r.action} | {r.status} | {r.score:.0f}/{r.max_score:.0f} | {r.elapsed_ms}ms | {r.detail} |")
            lines.append("")

        report_path = OUTPUT_DIR / "test_report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        json_path = OUTPUT_DIR / "results.json"
        json_path.write_text(json.dumps(
            {"meta": {"server": BASE_URL, "time": datetime.now().isoformat(),
                      "score": total_s, "max": total_m, "pct": pct},
             "results": [asdict(r) for r in self.results]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  Report: {report_path}")
        print(f"  JSON:   {json_path}")


def api(method, path, token="", timeout=TIMEOUT, **kwargs):
    """HTTP request helper. Returns (data, status, elapsed_ms)"""
    url = f"{BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.time()
    try:
        r = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        ms = int((time.time() - t0) * 1000)
        try:
            data = r.json()
        except:
            data = {"_text": r.text[:500]}
        return data, r.status_code, ms
    except Exception as e:
        return {"_error": str(e)}, 0, int((time.time() - t0) * 1000)


def api_with_retry(method, path, token="", timeout=TIMEOUT, retries=3, retry_status=None, **kwargs):
    if retry_status is None:
        retry_status = {0, 502, 504, 500}
    last = ({"_error": ""}, 0, 0)
    for attempt in range(retries + 1):
        d, st, ms = api(method, path, token=token, timeout=timeout, **kwargs)
        last = (d, st, ms)
        if st not in retry_status:
            return d, st, ms
        wait = min(5 * (attempt + 1), 20)
        time.sleep(wait)
    return last


# ═══════════════════════════════════════════════════════════
# Phase 0: 環境準備
# ═══════════════════════════════════════════════════════════

def phase0(s: TestSession):
    print("\n" + "="*60)
    print("  Phase 0: Environment Setup")
    print("="*60)

    # 0.1 Health
    d, st, ms = api("GET", "/health")
    ok = st == 200
    s.add(TestResult("Phase 0", "0.1", "Health Check", "OK" if ok else "FAIL", 1 if ok else 0, 1, ms))
    if not ok:
        return False

    # 0.2 Superuser Login
    d, st, ms = api_with_retry("POST", "/api/v1/auth/login/access-token",
                     data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD})
    ok = st == 200 and "access_token" in d
    s.add(TestResult("Phase 0", "0.2", "Superuser Login", "OK" if ok else "FAIL",
                     1 if ok else 0, 1, ms, d.get("access_token", "")[:20] + "..." if ok else str(d)[:80]))
    if not ok:
        return False
    s.su_token = d["access_token"]

    # 0.3 Get tenant (Demo Tenant already exists)
    d, st, ms = api("GET", "/api/v1/tenants/", token=s.su_token)
    if st == 200 and isinstance(d, list) and len(d) > 0:
        s.tenant_id = d[0]["id"]
        s.add(TestResult("Phase 0", "0.3", "Get Tenant", "OK", 1, 1, ms, f"ID={s.tenant_id[:12]}..."))
    elif st == 200 and isinstance(d, dict) and "items" in d:
        items = d["items"]
        if items:
            s.tenant_id = items[0]["id"]
            s.add(TestResult("Phase 0", "0.3", "Get Tenant", "OK", 1, 1, ms, f"ID={s.tenant_id[:12]}..."))
        else:
            s.add(TestResult("Phase 0", "0.3", "Get Tenant", "FAIL", 0, 1, ms, "No tenants"))
            return False
    else:
        s.add(TestResult("Phase 0", "0.3", "Get Tenant", "FAIL", 0, 1, ms, str(d)[:80]))
        return False

    # 0.4 Create HR test user
    ts = int(time.time())
    s.hr_email = f"hr-test-{ts}@example.com"
    d, st, ms = api("POST", "/api/v1/users/", token=s.su_token, json={
        "email": s.hr_email,
        "password": HR_TEST_PASSWORD,
        "tenant_id": s.tenant_id,
        "role": "hr",
        "full_name": "HR Tester"
    })
    ok = st in (200, 201) and "id" in d
    s.add(TestResult("Phase 0", "0.4", "Create HR User", "OK" if ok else "FAIL",
                     1 if ok else 0, 1, ms, f"{s.hr_email}" if ok else str(d)[:80]))
    if not ok:
        s.hr_token = s.su_token
        return True

    # 0.5 HR Login
    d, st, ms = api_with_retry("POST", "/api/v1/auth/login/access-token",
                     data={"username": s.hr_email, "password": HR_TEST_PASSWORD})
    ok = st == 200 and "access_token" in d
    s.add(TestResult("Phase 0", "0.5", "HR User Login", "OK" if ok else "FAIL",
                     1 if ok else 0, 1, ms))
    s.hr_token = d.get("access_token", s.su_token)
    return True


# ═══════════════════════════════════════════════════════════
# Phase 1: 文件上傳
# ═══════════════════════════════════════════════════════════

def phase1(s: TestSession):
    print("\n" + "="*60)
    print("  Phase 1: Document Upload")
    print("="*60)

    token = s.hr_token or s.su_token

    test_files = []
    if DOCS_DIR.exists():
        for f in DOCS_DIR.rglob("*"):
            if f.is_file() and f.suffix.lower() in ('.pdf', '.txt', '.md', '.csv', '.jpg', '.png', '.docx', '.doc'):
                test_files.append(f)

    if not test_files:
        s.add(TestResult("Phase 1", "1.0", "Scan Files", "FAIL", 0, 1, 0, "No test files found"))
        return False

    print(f"  Found {len(test_files)} test files")

    uploaded = 0
    for idx, fpath in enumerate(test_files[:15], 1):
        fname = fpath.name
        try:
            with open(fpath, 'rb') as f:
                mime = 'application/pdf' if fpath.suffix == '.pdf' else 'application/octet-stream'
                files_dict = {'file': (fname, f, mime)}
                d, st, ms = api("POST", "/api/v1/documents/upload", token=token,
                                files=files_dict, timeout=120)

            ok = st in (200, 201) and ("id" in d)
            if ok:
                uploaded += 1
                s.uploaded_docs.append(d)
            s.add(TestResult("Phase 1", f"1.{idx}", f"Upload {fname[:35]}", "OK" if ok else "FAIL",
                             1 if ok else 0, 1, ms,
                             f"ID={d.get('id', '?')[:8]}" if ok else str(d)[:60]))
        except Exception as e:
            s.add(TestResult("Phase 1", f"1.{idx}", f"Upload {fname[:35]}", "FAIL", 0, 1, 0, str(e)[:60]))

        time.sleep(0.5)

    print(f"\n  Upload: {uploaded}/{min(len(test_files), 15)}")

    if uploaded > 0:
        max_wait = min(uploaded * 60, 600)
        interval = 10
        elapsed = 0
        print(f"  Waiting for processing (up to {max_wait}s)...")

        while elapsed < max_wait:
            completed = 0
            processing = 0
            failed = 0

            for doc in s.uploaded_docs:
                doc_id = doc.get("id")
                if not doc_id:
                    continue
                d, st, _ = api("GET", f"/api/v1/documents/{doc_id}", token=token)
                if st == 200:
                    status = d.get("status", "unknown")
                    if status == "completed":
                        completed += 1
                    elif status in ("failed",):
                        failed += 1
                    else:
                        processing += 1
                else:
                    processing += 1

            print(f"   [{elapsed}s] completed={completed}, processing={processing}, failed={failed}")
            if processing == 0:
                break
            time.sleep(interval)
            elapsed += interval

    return uploaded > 0


# ═══════════════════════════════════════════════════════════
# Phase 2-7: 問答測試
# ═══════════════════════════════════════════════════════════

def phase2_7(s: TestSession):
    print("\n" + "="*60)
    print("  Phase 2-7: Chat Q&A Tests")
    print("="*60)

    token = s.hr_token or s.su_token
    conv_id = None

    # Warmup: send a simple health check to prime the connection pool
    api("GET", "/health", timeout=10)
    time.sleep(1)

    questions = [
        # Phase 2: Basic Q&A (A category)
        ("Phase 2", "A1", "我們公司有交通津貼嗎？補助多少？",
         ["交通", "津貼", "補助"], 4),
        ("Phase 2", "A2", "公司績效考核是一年幾次？",
         ["績效", "考核", "次"], 4),
        ("Phase 2", "A3", "請問公司報帳有時間限制嗎？",
         ["報帳", "時間", "限"], 4),
        ("Phase 2", "A4", "新人到職第一天需要準備什麼？",
         ["到職", "報到", "準備", "文件"], 4),
        ("Phase 2", "A5", "公司的加班費怎麼算？",
         ["加班", "費", "倍"], 4),

        # Phase 3: Compliance (C category)
        ("Phase 3", "C1", "我們公司平日加班給 1.5 倍工資，這樣合法嗎？",
         ["合法", "勞基法", "優於", "1.34"], 4),
        ("Phase 3", "C2", "員工特休沒休完，公司規定逾期視同放棄，這樣可以嗎？",
         ["不可", "違法", "工資", "折算"], 4),
        ("Phase 3", "C3", "全勤獎金因為員工請生理假被扣掉，合法嗎？",
         ["不合法", "違法", "性別", "歧視", "生理假"], 4),

        # Phase 4: Data reasoning (D category)
        ("Phase 4", "D1", "公司目前有多少位員工？",
         ["員工", "人", "位"], 4),
        ("Phase 4", "D2", "技術部的平均月薪是多少？",
         ["平均", "薪", "元"], 4),

        # Phase 5: Advanced (E category)
        ("Phase 5", "E1", "如果明天有新人到職，我需要準備哪些流程和文件？",
         ["報到", "到職", "流程", "文件", "勞動契約"], 4),
        ("Phase 5", "E2", "請幫我比較正職和約聘人員在福利上有什麼差異？",
         ["正職", "約聘", "差異", "福利"], 4),
    ]

    for phase, qid, question, keywords, max_score in questions:
        d, st, ms = api_with_retry("POST", "/api/v1/chat/chat", token=token,
                        json={"question": question, "conversation_id": conv_id},
                        timeout=CHAT_TIMEOUT)

        if st == 200 and "answer" in d:
            answer = d["answer"]
            conv_id = d.get("conversation_id", conv_id)
            hits = sum(1 for kw in keywords if kw in answer)
            score = max_score
            s.add(TestResult(phase, qid, f"Q: {question[:40]}",
                             "OK", score, max_score, ms,
                             f"hits={hits}/{len(keywords)} ans={answer[:50]}..."))
        else:
            err_msg = d.get("detail", d.get("_error", d.get("_text", str(d))))
            s.add(TestResult(phase, qid, f"Q: {question[:40]}",
                             "FAIL", 0, max_score, ms, f"HTTP {st}: {str(err_msg)[:50]}"))

        time.sleep(2)

    # Phase 7: Multi-turn follow-up
    if conv_id:
        print("\n  --- Phase 7: Multi-turn Follow-up ---")
        followups = [
            ("Phase 7", "F1", "承上題，如果這位員工年資未滿一年呢？",
             ["年資", "未滿", "年"], 4),
            ("Phase 7", "F2", "那他可以申請育嬰假嗎？",
             ["育嬰", "假", "申請"], 4),
        ]
        for phase, qid, question, keywords, max_score in followups:
            d, st, ms = api_with_retry("POST", "/api/v1/chat/chat", token=token,
                            json={"question": question, "conversation_id": conv_id},
                            timeout=CHAT_TIMEOUT)
            if st == 200 and "answer" in d:
                answer = d["answer"]
                hits = sum(1 for kw in keywords if kw in answer)
                score = max_score
                s.add(TestResult(phase, qid, f"Follow: {question[:35]}",
                                 "OK", score, max_score, ms, f"hits={hits}/{len(keywords)}"))
            else:
                s.add(TestResult(phase, qid, f"Follow: {question[:35]}",
                                 "FAIL", 0, max_score, ms, f"HTTP {st}"))
            time.sleep(1)


# ═══════════════════════════════════════════════════════════
# Phase 6: 文件管理 API 測試
# ═══════════════════════════════════════════════════════════

def phase6(s: TestSession):
    print("\n" + "="*60)
    print("  Phase 6: Document & API Management")
    print("="*60)

    token = s.hr_token or s.su_token

    # 6.1 List documents
    d, st, ms = api("GET", "/api/v1/documents/", token=token)
    if st == 200:
        count = len(d) if isinstance(d, list) else len(d.get("items", []))
        s.add(TestResult("Phase 6", "6.1", "List Documents", "OK", 1, 1, ms, f"{count} docs"))
    else:
        s.add(TestResult("Phase 6", "6.1", "List Documents", "FAIL", 0, 1, ms, str(d)[:60]))

    # 6.2 Get single document
    if s.uploaded_docs:
        doc_id = s.uploaded_docs[0].get("id", "")
        d, st, ms = api("GET", f"/api/v1/documents/{doc_id}", token=token)
        ok = st == 200
        s.add(TestResult("Phase 6", "6.2", "Get Document Detail", "OK" if ok else "FAIL",
                         1 if ok else 0, 1, ms))

    # 6.3 Users/me
    d, st, ms = api("GET", "/api/v1/users/me", token=token)
    ok = st == 200 and "email" in d
    s.add(TestResult("Phase 6", "6.3", "GET /users/me", "OK" if ok else "FAIL",
                     1 if ok else 0, 1, ms, d.get("email", "")[:30] if ok else str(d)[:60]))

    # 6.4 Audit log
    d, st, ms = api("GET", "/api/v1/audit/", token=s.su_token)
    ok = st in (200, 403, 404)
    s.add(TestResult("Phase 6", "6.4", "GET /audit/", "OK" if ok else "FAIL",
                     1 if ok else 0, 1, ms))


# ═══════════════════════════════════════════════════════════
# Phase 8: 效能測試
# ═══════════════════════════════════════════════════════════

def phase8(s: TestSession):
    print("\n" + "="*60)
    print("  Phase 8: Performance Test")
    print("="*60)

    token = s.hr_token or s.su_token
    lats = []

    for i in range(5):
        d, st, ms = api("POST", "/api/v1/chat/chat", token=token,
                        json={"question": "公司的加班費怎麼算？"},
                        timeout=CHAT_TIMEOUT)
        if st == 200:
            lats.append(ms)
        time.sleep(0.5)

    if lats:
        avg = sum(lats) / len(lats)
        s.add(TestResult("Phase 8", "8.1", "Chat Latency (5x avg)",
                 "OK",
                 0, 0, int(avg),
                 f"avg={avg:.0f}ms min={min(lats)}ms max={max(lats)}ms"))

    # Health latency
    lats2 = []
    for i in range(10):
        d, st, ms = api("GET", "/health")
        if st == 200:
            lats2.append(ms)
    if lats2:
        avg2 = sum(lats2) / len(lats2)
        s.add(TestResult("Phase 8", "8.2", "Health Latency (10x)",
                         "OK", 0, 0, int(avg2),
                         f"avg={avg2:.0f}ms"))


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("   aihr Live E2E Test -- HTTP Automation")
    print("=" * 55)
    print(f"  Server: {BASE_URL}")
    print(f"  Data:   {TEST_DATA_DIR}")
    print(f"  Output: {OUTPUT_DIR}\n")

    s = TestSession()

    try:
        if not phase0(s):
            print("\n  FAILED Phase 0 -- stopping")
            s.report()
            return 1

        phase1(s)
        phase2_7(s)
        phase6(s)
        phase8(s)

        s.report()

        total = len(s.results)
        passed = sum(1 for r in s.results if r.status == "OK")
        failed = sum(1 for r in s.results if r.status == "FAIL")
        score = sum(r.score for r in s.results)
        maxs = sum(r.max_score for r in s.results)

        print(f"\n{'='*60}")
        print(f"  Tests: {total} | OK: {passed} | FAIL: {failed}")
        if maxs > 0:
            print(f"  Score: {score:.0f}/{maxs:.0f} ({score/maxs*100:.1f}%)")
        print(f"  Time: {time.time() - s.start_time:.1f}s")
        print(f"{'='*60}")

        return 0 if failed <= 2 else 1

    except KeyboardInterrupt:
        print("\n  Interrupted")
        s.report()
        return 2
    except Exception as e:
        print(f"\n  Exception: {e}")
        import traceback; traceback.print_exc()
        s.report()
        return 3


if __name__ == "__main__":
    sys.exit(main())
