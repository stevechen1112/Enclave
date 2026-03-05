"""aihr 系統完整測試執行器 v3
===============================
- 嚴格評分：數值比對 (±5%)、合規方向檢查、關鍵詞比對
- 並行問答 (ThreadPoolExecutor)，Phase 2-6 同時 5 個請求
- 並行文件上傳
- 支援本地 + 雲端（透過 AIHR_BASE_URL 環境變數）
- 即時進度顯示
- 結構化 JSON + Markdown 報告 + 詳細日誌

用法:
  python scripts/run_tests.py                  # 執行所有階段 (本地)
  python scripts/run_tests.py --phase 0        # 只執行 Phase 0
  python scripts/run_tests.py --phase 2 --phase 3
  python scripts/run_tests.py --resume         # 從上次中斷處繼續
  python scripts/run_tests.py --workers 8      # 並行數 (預設 5)

  # 雲端測試:
  AIHR_BASE_URL=http://api.172-237-5-254.sslip.io python scripts/run_tests.py
"""

import json, time, os, sys, argparse, traceback, threading, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import urllib.request, urllib.parse, urllib.error, ssl

# ── 常數 ─────────────────────────────────────

BASE_URL = os.getenv("AIHR_BASE_URL", "http://localhost:8000")
CORE_API = os.getenv("AIHR_CORE_API", "http://localhost:8000")
SUPERUSER_EMAIL = os.getenv("AIHR_SUPERUSER_EMAIL", "admin@example.com")
SUPERUSER_PASS = os.getenv("AIHR_SUPERUSER_PASS", "admin123")
HR_EMAIL = os.getenv("AIHR_HR_EMAIL", "hr@taiyutech.com")
HR_PASS = os.getenv("AIHR_HR_PASS", "Test1234!")
TENANT_NAME = os.getenv("AIHR_TENANT_NAME", "泰宇科技股份有限公司")
TW = timezone(timedelta(hours=8))
TEST_DATA = Path(__file__).parent.parent / "test-data"
DOCS_DIR = TEST_DATA / "company-documents"
LOG_DIR = TEST_DATA / "test-results"
LOG_DIR.mkdir(parents=True, exist_ok=True)
MAX_WORKERS = 5
MAX_SCORE = 4

def _extract_numbers(text: str):
    nums = re.findall(r"\d+(?:[,.]\d+)?", text or "")
    return [float(n.replace(",", "")) for n in nums]

def _numbers_match(expected: str, answer: str) -> Optional[bool]:
    """Check if key numbers in expected appear in answer (±5% tolerance)."""
    exp_nums = _extract_numbers(expected)
    if not exp_nums:
        return None
    ans_nums = _extract_numbers(answer)
    if not ans_nums:
        return False
    for en in exp_nums:
        tol = max(1.0, abs(en) * 0.05)
        if not any(abs(an - en) <= tol for an in ans_nums):
            return False
    return True

def _terms_match(expected: str, answer: str) -> bool:
    if not expected or not answer:
        return False
    parts = re.split(r"[，。、,;；\s/]+", expected)
    terms = [p for p in parts if len(p) >= 2][:5]
    if not terms:
        return False
    return all(t in answer for t in terms)

# ── 合規題方向判斷 ──────────────────────────

_COMPLIANCE_RULES = {
    # qid → (direction, keywords_any)
    # direction: "illegal" = 必須判斷違法, "legal" = 必須判斷合法/優於法令
    "C1": ("legal",  ["合法", "優於", "高於"]),
    "C2": ("illegal", ["違反", "違法", "不可", "不合法", "不行", "不得"]),
    "C3": ("illegal", ["違反", "違法", "不合法", "不可", "不得", "不對"]),
    "C4": ("legal",  ["合法", "可以", "原則上"]),
    "C5": ("legal",  ["合法", "優於", "高於", "多於", "超過", "超出", "6 天", "六天"]),
    "C6": ("illegal", ["不可", "不能", "無法", "不得", "資遣費", "違法", "需要", "不構成"]),
}

def _compliance_direction_ok(qid: str, answer: str) -> Optional[bool]:
    """Check if the answer judges the compliance direction correctly.
    Returns None if qid is not a compliance question."""
    rule = _COMPLIANCE_RULES.get(qid)
    if not rule:
        return None
    direction, keywords = rule
    return any(kw in answer for kw in keywords)

# ── HTTP ─────────────────────────────────────

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def http_request(method, url, body=None, headers=None,
                 form_data=None, file_path=None, file_field="file"):
    headers = dict(headers or {})
    if file_path:
        boundary = f"----Boundary{int(time.time()*1000)}"
        fname = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            fdata = f.read()
        parts = [f'--{boundary}'.encode(),
                 f'Content-Disposition: form-data; name="{file_field}"; filename="{fname}"'.encode(),
                 b'Content-Type: application/octet-stream', b'', fdata,
                 f'--{boundary}--'.encode()]
        raw = b'\r\n'.join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif form_data:
        raw = form_data.encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body:
        raw = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    else:
        raw = None

    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, context=_ssl_ctx, timeout=120)
        st, rb = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        st = e.code
        rb = e.read().decode() if e.fp else str(e)
    except Exception as e:
        st, rb = 0, str(e)
    ms = int((time.time() - t0) * 1000)
    try:
        rj = json.loads(rb)
    except Exception:
        rj = {"raw": rb[:2000]}
    return st, rj, ms

# ── 日誌 (thread-safe) ─────────────────────

class TestLogger:
    def __init__(self, run_id):
        self.run_id = run_id
        self.run_dir = LOG_DIR / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.run_dir / "test_log.jsonl"
        self.detail_path = self.run_dir / "test_detail.log"
        self.summary_path = self.run_dir / "test_report.md"
        self.phases = {}
        self.current_phase = None
        self.start_time = datetime.now(TW)
        self._lock = threading.Lock()
        self._w(f"{'='*60}")
        self._w(f"  aihr 測試 | Run {run_id} | {self.start_time:%Y-%m-%d %H:%M:%S}")
        self._w(f"{'='*60}\n")

    def _jl(self, rec):
        rec["_ts"] = datetime.now(TW).isoformat()
        with self._lock:
            with open(self.json_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _w(self, msg):
        ts = datetime.now(TW).strftime("%H:%M:%S")
        with self._lock:
            with open(self.detail_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")

    def phase_start(self, pid, title):
        self.current_phase = pid
        self.phases[pid] = {"phase_id": pid, "title": title,
                            "start_time": datetime.now(TW).isoformat(),
                            "end_time": None, "duration_sec": None,
                            "status": "running", "steps": [], "summary": {}}
        self._jl({"event": "phase_start", "phase": pid, "title": title})
        self._w(f"\n{'─'*60}\n▶ Phase {pid}: {title}\n{'─'*60}")

    def phase_end(self, pid, status="completed", summary=None):
        p = self.phases[pid]
        p["end_time"] = datetime.now(TW).isoformat()
        p["duration_sec"] = round((datetime.now(TW) - datetime.fromisoformat(p["start_time"])).total_seconds(), 1)
        p["status"] = status
        if summary:
            p["summary"] = summary
        self._jl({"event": "phase_end", "phase": pid, "status": status,
                   "duration_sec": p["duration_sec"], "summary": summary or {}})
        self._w(f"◀ Phase {pid} {status} ({p['duration_sec']}s)")

    def log_step(self, sid, action, request=None, response=None,
                 status="ok", duration_ms=0, score=None, max_score=None, notes=""):
        rec = {"event": "step", "phase": self.current_phase, "step_id": sid,
               "action": action, "status": status, "duration_ms": duration_ms,
               "score": score, "max_score": max_score, "notes": notes}
        if request: rec["request"] = request
        if response: rec["response"] = response
        self._jl(rec)
        sc = f" [{score}/{max_score}]" if score is not None else ""
        ico = {"ok": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(status, "●")
        self._w(f"  {ico} {sid}: {action[:60]}{sc} ({duration_ms}ms)")
        if notes: self._w(f"     → {notes}")
        with self._lock:
            if self.current_phase in self.phases:
                self.phases[self.current_phase]["steps"].append(rec)
        return rec

    def log_api(self, sid, method, url, req_body=None, resp_body=None,
                status_code=0, duration_ms=0, notes="", expected_statuses=None):
        rq = {"method": method, "url": url}
        if req_body: rq["body"] = req_body
        rsp = {"status_code": status_code}
        if resp_body: rsp["body"] = resp_body
        ok_set = expected_statuses or range(200, 300)
        st = "ok" if status_code in ok_set else "fail"
        return self.log_step(sid, f"{method} {url}", request=rq, response=rsp,
                             status=st, duration_ms=duration_ms, notes=notes)

    def log_question(self, qid, question, expected, answer, sources=None,
                     score=0, max_score=3, duration_ms=0, notes="", conv_id=None):
        rq = {"question": question, "expected": expected}
        if conv_id: rq["conversation_id"] = conv_id
        rsp = {"answer": answer, "sources": sources or [],
               "answer_length": len(answer) if answer else 0}
        st = "ok" if score >= 2 else ("warn" if score == 1 else "fail")
        return self.log_step(qid, f"Q: {question[:50]}...", request=rq, response=rsp,
                             status=st, score=score, max_score=max_score,
                             duration_ms=duration_ms, notes=notes)

    def log_error(self, sid, err):
        tb = traceback.format_exc()
        self._jl({"event": "error", "phase": self.current_phase,
                   "step_id": sid, "error": str(err), "traceback": tb})
        self._w(f"  ❌ ERROR {sid}: {err}")

    def save_checkpoint(self):
        with open(self.run_dir / "checkpoint.json", "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id, "timestamp": datetime.now(TW).isoformat(),
                        "phases": {k: v["status"] for k, v in self.phases.items()}},
                       f, ensure_ascii=False, indent=2)

    def generate_report(self):
        end = datetime.now(TW)
        total = (end - self.start_time).total_seconds()
        L = [f"# aihr 系統測試報告\n",
             f"**Run**: `{self.run_id}` | **目標**: `{BASE_URL}` | **時間**: {self.start_time:%H:%M}~{end:%H:%M} | **耗時**: {total:.0f}s\n",
             "## 階段總覽\n",
             "| 階段 | 標題 | 狀態 | 耗時 | 得分 | 得分率 |",
             "|------|------|------|------|------|--------|"]
        ts, tm = 0, 0
        for pid, p in self.phases.items():
            scored = [s for s in p["steps"] if s.get("score") is not None]
            ss = sum(s["score"] for s in scored)
            sm = sum(s["max_score"] for s in scored) if scored else 0
            ts += ss; tm += sm
            pct = f"{ss/sm*100:.0f}%" if sm else "N/A"
            ico = {"completed": "✅", "failed": "❌", "skipped": "⏭️",
                   "completed_with_errors": "⚠️"}.get(p["status"], "●")
            L.append(f"| {pid} | {p['title'][:20]} | {ico} | {p.get('duration_sec',0):.0f}s | {ss}/{sm} | {pct} |")
        op = ts/tm*100 if tm else 0
        grade = "🏆優秀" if op >= 85 else "✅合格" if op >= 70 else "⚠️待改進" if op >= 50 else "❌不合格"
        L.append(f"\n**總分: {ts}/{tm} ({op:.1f}%) — {grade}**\n")
        L.append("---\n## 詳細結果\n")
        for pid, p in self.phases.items():
            L.append(f"### Phase {pid}: {p['title']}\n")
            L.append(f"狀態: {p['status']} | 耗時: {p.get('duration_sec',0):.1f}s\n")
            if p.get("summary"):
                L.append(f"摘要: {json.dumps(p['summary'], ensure_ascii=False)}\n")
            steps = p.get("steps", [])
            if steps:
                L.append("| # | 動作 | 狀態 | 評分 | 耗時 | 備註 |")
                L.append("|---|------|------|------|------|------|")
                for s in steps:
                    ico = {"ok":"✅","fail":"❌","warn":"⚠️","skip":"⏭️"}.get(s["status"],"●")
                    sc = f"{s['score']}/{s['max_score']}" if s.get("score") is not None else "-"
                    L.append(f"| {s['step_id']} | {s['action'][:35]} | {ico} | {sc} | {s['duration_ms']}ms | {s.get('notes','')[:25]} |")
            L.append("")
        L.append("---\n## 問答詳細\n")
        for pid, p in self.phases.items():
            qs = [s for s in p["steps"] if s.get("request", {}).get("question")]
            if not qs: continue
            L.append(f"### Phase {pid}\n")
            for s in qs:
                L.append(f"**{s['step_id']}** | 評分: {s.get('score','-')}/{s.get('max_score','-')} | {s['duration_ms']}ms")
                L.append(f"- 問: {s['request']['question']}")
                L.append(f"- 期望: {s['request'].get('expected','')}")
                ans = s.get("response",{}).get("answer","")
                L.append(f"- 答: {ans[:500]}")
                src = s.get("response",{}).get("sources",[])
                if src: L.append(f"- 來源: {src[:3]}")
                L.append("")
        L.append(f"\n---\n日誌: `{self.run_dir}`")
        report = "\n".join(L)
        with open(self.summary_path, "w", encoding="utf-8") as f:
            f.write(report)
        self._w(f"\n{'='*60}\n  報告: {self.summary_path}\n  總分: {ts}/{tm} ({op:.1f}%)\n{'='*60}")
        return report

# ── 測試執行 ────────────────────────────────

class TestRunner:
    def __init__(self, logger, workers=MAX_WORKERS):
        self.log = logger
        self.tokens = {}
        self.tenant_id = None
        self.doc_ids = {}
        self.workers = workers

    def _get_token(self):
        return self.tokens.get("hr") or self.tokens.get("superuser")

    def _quick_login(self):
        """Resume 時快速重新登入（不記錄 log）"""
        try:
            form = f"username={urllib.parse.quote(SUPERUSER_EMAIL)}&password={urllib.parse.quote(SUPERUSER_PASS)}"
            st, resp, _ = http_request("POST", f"{BASE_URL}/api/v1/auth/login/access-token", form_data=form)
            if st == 200 and resp.get("access_token"):
                self.tokens["superuser"] = resp["access_token"]
                print("    ✅ superuser token ok", flush=True)
                # 取得 tenant_id
                st2, r2, _ = http_request("GET", f"{BASE_URL}/api/v1/tenants/",
                                          headers={"Authorization": f"Bearer {self.tokens['superuser']}"})
                tl = r2 if isinstance(r2, list) else r2.get("items", r2.get("data", []))
                for t in (tl if isinstance(tl, list) else []):
                    if t.get("name") == TENANT_NAME:
                        self.tenant_id = t["id"]; break
        except: pass
        try:
            form = f"username={urllib.parse.quote(HR_EMAIL)}&password={urllib.parse.quote(HR_PASS)}"
            st, resp, _ = http_request("POST", f"{BASE_URL}/api/v1/auth/login/access-token", form_data=form)
            if st == 200 and resp.get("access_token"):
                self.tokens["hr"] = resp["access_token"]
                print("    ✅ hr token ok", flush=True)
        except: pass

    def _ask_one(self, qid, question, expected, conv_id=None):
        """發送一題（thread-safe）— 嚴格評分版 v3

        評分邏輯 (MAX_SCORE=4):
          +1  HTTP 200 且 answer 非空
          +1  答案實質性 (>50 字) 且附帶 sources
          +1  數值比對通過 (±5%) 或 關鍵詞全部命中
          +1  合規方向正確 (C 類) 或 引用來源正確 (其他)

        若數值比對明確失敗 (有期望數值但答案不含)，上限 2 分。
        若合規方向判錯，上限 1 分。
        """
        token = self._get_token()
        if not token:
            self.log.log_question(qid, question, expected, "(no token)", score=0, max_score=MAX_SCORE, notes="無 token")
            return {}
        body = {"question": question, "top_k": 5}
        if conv_id:
            body["conversation_id"] = conv_id
        try:
            st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/chat/chat",
                                        body=body,
                                        headers={"Authorization": f"Bearer {token}"})
            answer = resp.get("answer", "")
            sources = resp.get("sources", [])
            score = 0
            max_score = MAX_SCORE
            scoring_notes = []

            if st != 200 or not answer:
                scoring_notes.append(f"HTTP {st}" if st != 200 else "empty answer")
            else:
                # Dimension 1: 有回答
                score += 1
                scoring_notes.append("has_answer")

                # Dimension 2: 實質性 (長度 + 來源)
                has_substance = len(answer) > 30 and len(sources) > 0
                if has_substance:
                    score += 1
                    scoring_notes.append("substance")

                # Dimension 3: 正確性 (數值 或 關鍵詞)
                num_match = _numbers_match(expected, answer)
                terms_ok = _terms_match(expected, answer)
                if num_match is True:
                    score += 1
                    scoring_notes.append("num_match")
                elif num_match is False:
                    # 有期望數值但不符 → 上限 2 分
                    score = min(score, 2)
                    scoring_notes.append("num_MISMATCH")
                elif terms_ok:
                    score += 1
                    scoring_notes.append("terms_match")

                # Dimension 4: 合規方向 (C 類) 或 有引用來源 (其他)
                compliance = _compliance_direction_ok(qid, answer)
                if compliance is True:
                    score += 1
                    scoring_notes.append("compliance_ok")
                elif compliance is False:
                    # 合規方向判錯 → 上限 1 分
                    score = min(score, 1)
                    scoring_notes.append("compliance_WRONG")
                else:
                    # 非合規題：有來源 +1
                    if sources:
                        score += 1
                        scoring_notes.append("has_sources")

            score = min(score, max_score)
            notes_str = ",".join(scoring_notes)
            self.log.log_question(qid, question, expected, answer,
                                  sources=sources, score=score, max_score=max_score, duration_ms=ms,
                                  conv_id=resp.get("conversation_id"),
                                  notes=notes_str)
            ico = "✅" if score >= 3 else "⚠️" if score >= 2 else "❌"
            print(f"    {ico} {qid} [{score}/{max_score}] ({ms}ms) {notes_str}", flush=True)
            return resp
        except Exception as e:
            self.log.log_error(qid, e)
            self.log.log_question(qid, question, expected, f"ERR: {e}", score=0, max_score=MAX_SCORE, notes="exception")
            print(f"    ❌ {qid} ERROR", flush=True)
            return {}

    def _ask_batch(self, questions, phase_id, title):
        """並行發送一批問題"""
        self.log.phase_start(phase_id, title)
        n = len(questions)
        print(f"    ⚡ 並行 {n} 題 (workers={self.workers})", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {pool.submit(self._ask_one, qid, q, exp): qid
                    for qid, q, exp in questions}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception as e:
                    self.log.log_error(futs[fut], e)
        elapsed = time.time() - t0
        print(f"    📊 {n} 題完成 ({elapsed:.1f}s, 平均 {elapsed/n:.1f}s/題)", flush=True)
        self.log.save_checkpoint()
        self.log.phase_end(phase_id, "completed", {"questions": n, "elapsed_sec": round(elapsed, 1)})

    # ── Phase 0 ──

    def _cleanup_tenant_data(self):
        """清除測試租戶的舊文件資料，確保每次測試乾淨起跑。
        僅在本地 (localhost) 環境可用直接 DB 清理。
        雲端環境跳過此步驟（透過 API 已足夠）。
        """
        if "localhost" not in BASE_URL and "127.0.0.1" not in BASE_URL:
            print("    ⏭️ 雲端模式，跳過 DB 直接清理")
            return
        try:
            from app.db.session import SessionLocal
            from app.models.tenant import Tenant
            from app.models.document import Document, DocumentChunk
            db = SessionLocal()
            tenant = db.query(Tenant).filter(Tenant.name == TENANT_NAME).first()
            if tenant:
                cc = db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant.id).delete(synchronize_session=False)
                dc = db.query(Document).filter(Document.tenant_id == tenant.id).delete(synchronize_session=False)
                db.commit()
                if dc or cc:
                    print(f"    🧹 清理舊資料: {dc} docs, {cc} chunks")
            db.close()
        except Exception as e:
            print(f"    ⚠️ 清理失敗(可忽略): {e}")

    def phase_0_setup(self):
        self.log.phase_start("0", "環境準備")
        ok, fail = 0, 0

        # 健康檢查 (並行)
        with ThreadPoolExecutor(2) as pool:
            f1 = pool.submit(http_request, "GET", f"{BASE_URL}/health")
            f2 = pool.submit(http_request, "GET", f"{CORE_API}/health")
            for label, fut in [("aihr", f1), ("core", f2)]:
                try:
                    st, resp, ms = fut.result()
                    sid = "0.1" if label == "aihr" else "0.2"
                    self.log.log_api(sid, "GET", f"/{label}/health", resp_body=resp,
                                     status_code=st, duration_ms=ms,
                                     notes=f"{label} ok" if st == 200 else f"{label} fail")
                    ok += 1 if st == 200 else 0
                    fail += 0 if st == 200 else 1
                except Exception as e:
                    self.log.log_error(f"0.{label}", e); fail += 1

        # Superuser 登入
        try:
            form = f"username={urllib.parse.quote(SUPERUSER_EMAIL)}&password={urllib.parse.quote(SUPERUSER_PASS)}"
            st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/auth/login/access-token", form_data=form)
            self.log.log_api("0.3", "POST", "/auth/login(su)", status_code=st, duration_ms=ms,
                              notes="token ok" if resp.get("access_token") else f"fail:{st}")
            if st == 200 and resp.get("access_token"):
                self.tokens["superuser"] = resp["access_token"]; ok += 1
            else:
                fail += 1
        except Exception as e:
            self.log.log_error("0.3", e); fail += 1

        # 建立租戶
        if "superuser" in self.tokens:
            try:
                tb = {"name": TENANT_NAME, "plan": "enterprise", "max_documents": 100,
                      "max_storage_mb": 1000, "max_users": 50, "monthly_query_limit": 10000}
                st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/tenants/", body=tb,
                                            headers={"Authorization": f"Bearer {self.tokens['superuser']}"})
                if st in (200, 201) and resp.get("id"):
                    self.tenant_id = resp["id"]; ok += 1
                elif st == 400:
                    st2, r2, _ = http_request("GET", f"{BASE_URL}/api/v1/tenants/",
                                              headers={"Authorization": f"Bearer {self.tokens['superuser']}"})
                    tl = r2 if isinstance(r2, list) else r2.get("items", r2.get("data", []))
                    for t in (tl if isinstance(tl, list) else []):
                        if t.get("name") == TENANT_NAME:
                            self.tenant_id = t["id"]; break
                    ok += 1 if self.tenant_id else 0
                    fail += 0 if self.tenant_id else 1
                else:
                    fail += 1
                self.log.log_api("0.4", "POST", "/tenants/", status_code=st, duration_ms=ms,
                                  notes=f"tenant_id={self.tenant_id}",
                                  expected_statuses=[200, 201, 400])
            except Exception as e:
                self.log.log_error("0.4", e); fail += 1

        # 清理舊測試資料（拿到 tenant 後立即清理）
        if self.tenant_id:
            self._cleanup_tenant_data()

        # 建立 HR + 登入
        if self.tenant_id and "superuser" in self.tokens:
            try:
                ub = {"email": HR_EMAIL, "password": HR_PASS, "full_name": "李小芳",
                      "tenant_id": self.tenant_id, "role": "admin"}
                st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/users/", body=ub,
                                            headers={"Authorization": f"Bearer {self.tokens['superuser']}"})
                self.log.log_api("0.5", "POST", "/users/", status_code=st, duration_ms=ms,
                                  expected_statuses=[200, 201, 400])
                ok += 1 if st in (200, 201, 400) else 0
            except Exception as e:
                self.log.log_error("0.5", e)
        try:
            form = f"username={urllib.parse.quote(HR_EMAIL)}&password={urllib.parse.quote(HR_PASS)}"
            st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/auth/login/access-token", form_data=form)
            if st == 200 and resp.get("access_token"):
                self.tokens["hr"] = resp["access_token"]; ok += 1
            else:
                fail += 1
            self.log.log_api("0.6", "POST", "/auth/login(hr)", status_code=st, duration_ms=ms,
                              notes="hr token ok" if "hr" in self.tokens else "hr fail")
        except Exception as e:
            self.log.log_error("0.6", e); fail += 1

        self.log.save_checkpoint()
        self.log.phase_end("0", "completed" if fail == 0 else "completed_with_errors",
                           {"ok": ok, "fail": fail, "has_su": "superuser" in self.tokens,
                            "has_hr": "hr" in self.tokens, "tenant": self.tenant_id})

    # ── Phase 1: 並行上傳 ──

    def phase_1_upload(self):
        self.log.phase_start("1", "文件上傳 (11 檔)")
        token = self._get_token()
        if not token:
            self.log.log_step("1.0", "no token", status="fail")
            self.log.phase_end("1", "failed"); return

        files = [
            ("hr-regulations", "員工手冊-第一章-總則.pdf"),
            ("hr-regulations", "獎懲管理辦法.pdf"),
            ("sop", "新人到職SOP.pdf"),
            ("sop", "報帳作業規範.pdf"),
            ("employee-data", "員工名冊.csv"),
            ("payroll", "202601-E007-劉志明-薪資條.pdf"),
            ("forms", "請假單範本-E012-周秀蘭.pdf"),
            ("contracts", "勞動契約書-謝雅玲.pdf"),
            ("health-records", "健康檢查報告-E016-高淑珍.pdf"),
            ("official-forms", "變更登記表A.jpg"),
            ("official-forms", "變更登記表B.jpg"),
        ]

        def upload_one(i, folder, fname):
            fpath = DOCS_DIR / folder / fname
            if not fpath.exists():
                self.log.log_step(f"1.{i}", f"not found: {fname}", status="fail")
                return None
            st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/documents/upload",
                                        headers={"Authorization": f"Bearer {token}"},
                                        file_path=str(fpath))
            doc_id = resp.get("id", "?")
            self.log.log_api(f"1.{i}", "POST", f"/upload({fname[:10]})",
                             status_code=st, duration_ms=ms, notes=f"id={doc_id}")
            ico = "✅" if st in (200, 201) else "❌"
            print(f"    {ico} {fname} ({ms}ms)", flush=True)
            return (fname, doc_id) if st in (200, 201) else None

        print(f"    ⚡ 並行上傳 {len(files)} 檔", flush=True)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = [pool.submit(upload_one, i, fo, fn) for i, (fo, fn) in enumerate(files, 1)]
            for fut in as_completed(futs):
                r = fut.result()
                if r:
                    self.doc_ids[r[0]] = r[1]

        # 快速檢查狀態
        time.sleep(2)
        for fname, did in list(self.doc_ids.items())[:3]:
            try:
                st, resp, ms = http_request("GET", f"{BASE_URL}/api/v1/documents/{did}",
                                            headers={"Authorization": f"Bearer {token}"})
                self.log.log_step(f"1.chk", f"{fname[:10]}: {resp.get('status','?')}",
                                  duration_ms=ms, status="ok")
            except: pass

        self.log.save_checkpoint()
        self.log.phase_end("1", "completed", {"uploaded": len(self.doc_ids), "total": len(files)})

    # ── Phase 2-6: 並行問答 ──

    def phase_2_basic_qa(self):
        self._ask_batch([
            ("A1", "我們公司有交通津貼嗎？補助多少？", "500-2,000 元"),
            ("A2", "公司績效考核是一年幾次？", "2 次（6月/12月）"),
            ("A3", "請問公司報帳有時間限制嗎？", "30 日內"),
            ("A4", "什麼情況下可以報帳計程車費用？", "重物/深夜/緊急，限 1,000 元"),
            ("A5", "新人第一天報到需要準備哪些文件？", "8 項文件清單"),
            ("B1", "員工年資 3 年 2 個月，特休有幾天？", "14 天"),
            ("B2", "平日加班 3 小時，月薪 48,000 元，加班費怎麼算？", "870 元"),
            ("B3", "員工年資 5 年 3 個月被資遣，月薪 55,000，資遣費多少？", "約 151,250 元"),
            ("B4", "女性員工到職 8 個月懷孕生產，產假有給薪嗎？", "56 天有薪"),
            ("B5", "年終獎金算不算工資？", "視個案判斷"),
        ], "2", "基礎問答 (A×5 + B×5)")

    def phase_3_compliance(self):
        self._ask_batch([
            ("C1", "我們公司平日加班給 1.5 倍工資，這樣合法嗎？", "優於法定 1.34 倍，合法"),
            ("C2", "員工特休沒休完，公司規定逾期視同放棄，這樣可以嗎？", "違反勞基法§38，應給付未休工資"),
            ("C3", "女員工請生理假被扣全勤獎金，公司這樣對嗎？", "違反性平法§14，前 3 天不扣"),
            ("C4", "我們公司試用期薪資打 9 折，這樣合法嗎？", "合法但不得低於基本工資"),
            ("C5", "請問配偶的祖父母過世，我可以請幾天喪假？", "法定 3 天，公司給 6 天優於法令"),
            ("C6", "員工連續兩次考績 D 等，公司可以直接解僱嗎？", "非勞基法§12 事由，需資遣費"),
        ], "3", "合規偵測 ★核心 (C×6)")

    def phase_4_data_reasoning(self):
        self._ask_batch([
            ("D1", "員工編號 E003 陳建宏今年可以休幾天特休？", "15 天（年資 8.9 年）"),
            ("D2", "技術部的平均月薪是多少？", "59,833 元"),
            ("D3", "如果今天要資遣 E007 劉志明，需要付多少資遣費？", "約 156,000 元"),
            ("D4", "公司目前年資最深的員工是誰？年資幾年？", "E005 張志豪 9.6 年"),
            ("D5", "公司女性員工占比多少？", "50%（10/20）"),
        ], "4", "數據推理 (D×5)")

    def phase_5_advanced(self):
        self._ask_batch([
            ("E1", "請問變更登記表上的公司統一編號是多少？", "統一編號 61846629"),
            ("E2", "女員工懷孕後主管說「懷孕就不能加班，考績會打比較低」，這樣合法嗎？", "違反性平法§11、§21"),
            ("E3", "員工請職業災害醫療期間，公司因業務緊縮想資遣他，可以嗎？", "不可以，勞基法§13"),
            ("E4", "昨天颱風縣市政府宣布停班停課，但老闆說我們要上班，合法嗎？", "颱風假為建議性質"),
            ("E5", "我們公司說工程師都是責任制，不用給加班費，這樣對嗎？", "一般工程師不適用責任制"),
            ("E6", "我想離職，公司說要提前 3 個月離職，不然不給資遣費，可以這樣嗎？", "自請離職無資遣費"),
        ], "5", "進階能力 (E×6)")

    def phase_6_cross_doc(self):
        self._ask_batch([
            ("F1", "劉志明這個月實領多少薪水？包含哪些項目？", "55,244 元"),
            ("F2", "員工月薪 54,200，勞保費自付多少？", "956 元"),
            ("G1", "請特休需要誰核准？", "直屬主管 → 人資部門"),
            ("G2", "周秀蘭的特休還剩幾天？", "5 天"),
            ("H1", "新人試用期多久？薪資有差異嗎？", "3 個月，63,000→70,000"),
            ("H2", "年資 2 年的員工要離職，需提前幾天？", "20 天"),
            ("I1", "高淑珍的健檢報告有異常嗎？", "無明顯異常，輕度近視"),
            ("I2", "長時間用電腦工作，醫生建議什麼？", "每小時休息 10 分鐘"),
        ], "6", "跨文件綜合 (F-I ×8)")

    # ── Phase 7: 多輪 (必須串行) ──

    def phase_7_multiturn(self):
        self.log.phase_start("7", "多輪對話 (2 組情境)")
        print("    🔗 情境 1: 離職諮詢 (4 輪)", flush=True)
        conv = None
        for qid, q, exp in [("7.1.1", "我年資 3 年想離職，需要提前幾天通知？", "20 天"),
                             ("7.1.2", "那我有資遣費嗎？", "自請離職無資遣費"),
                             ("7.1.3", "如果是公司要我走呢？", "需符合勞基法§11"),
                             ("7.1.4", "資遣費怎麼算？", "年資×1/2 個月工資")]:
            r = self._ask_one(qid, q, exp, conv_id=conv)
            if r: conv = r.get("conversation_id")
        print("    🔗 情境 2: HR 查員工 (4 輪)", flush=True)
        conv = None
        for qid, q, exp in [("7.2.1", "E007 劉志明是哪個部門的？薪水多少？", "技術部 52,000"),
                             ("7.2.2", "他這個月加班費領了多少？", "6,622 元"),
                             ("7.2.3", "公司加班費計算方式合法嗎？", "員工手冊 vs 勞基法§24"),
                             ("7.2.4", "那如果要資遣他要給多少資遣費？", "52,000×6.2×0.5")]:
            r = self._ask_one(qid, q, exp, conv_id=conv)
            if r: conv = r.get("conversation_id")
        self.log.save_checkpoint()
        self.log.phase_end("7", "completed")

    # ── Phase 8: 效能 ──

    def phase_8_performance(self):
        self.log.phase_start("8", "效能測試")
        token = self._get_token()
        if not token:
            self.log.phase_end("8", "skipped"); return
        qs = ["公司上班時間是幾點到幾點？", "勞基法規定的基本工資是多少？",
              "E001 王大明的職稱是什麼？", "請問請婚假需要給薪嗎？", "技術部有幾位員工？"]
        times = []
        for i, q in enumerate(qs, 1):
            try:
                st, resp, ms = http_request("POST", f"{BASE_URL}/api/v1/chat/chat",
                                            body={"question": q, "top_k": 3},
                                            headers={"Authorization": f"Bearer {token}"})
                times.append(ms)
                self.log.log_step(f"P{i}", f"{ms}ms: {q[:25]}", duration_ms=ms,
                                  notes=f"len={len(resp.get('answer',''))}")
                print(f"    ⏱ P{i}: {ms}ms", flush=True)
            except Exception as e:
                self.log.log_error(f"P{i}", e)
        if times:
            avg, mx, mn = sum(times)//len(times), max(times), min(times)
            self.log.log_step("P.sum", f"Avg={avg}ms Min={mn}ms Max={mx}ms",
                              duration_ms=avg, status="ok" if avg < 10000 else "warn")
        self.log.save_checkpoint()
        self.log.phase_end("8", "completed",
                           {"avg": avg, "max": mx, "min": mn, "n": len(times)} if times else {})


# ── main ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="aihr 測試執行器 v2")
    parser.add_argument("--phase", type=int, action="append", help="指定階段 (0-8)")
    parser.add_argument("--resume", action="store_true", help="從中斷點繼續")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"並行數 (預設 {MAX_WORKERS})")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now(TW).strftime("run_%Y%m%d_%H%M%S")
    done = set()
    if args.resume:
        latest = sorted(LOG_DIR.glob("run_*/checkpoint.json"))
        if latest:
            ckpt = json.loads(latest[-1].read_text())
            run_id = ckpt["run_id"]
            done = {k for k, v in ckpt.get("phases", {}).items() if v == "completed"}

    logger = TestLogger(run_id)
    runner = TestRunner(logger, workers=args.workers)
    phases = args.phase or list(range(9))
    phase_map = {0: runner.phase_0_setup, 1: runner.phase_1_upload,
                 2: runner.phase_2_basic_qa, 3: runner.phase_3_compliance,
                 4: runner.phase_4_data_reasoning, 5: runner.phase_5_advanced,
                 6: runner.phase_6_cross_doc, 7: runner.phase_7_multiturn,
                 8: runner.phase_8_performance}

    # Resume 時重新取得 token（Phase 0 不重跑但要登入）
    if done and "0" in done:
        print("  🔑 Resume: 重新登入取得 token...", flush=True)
        runner._quick_login()

    print(f"{'='*50}")
    print(f"  aihr 測試 v3 | {run_id} | workers={args.workers}")
    print(f"  目標: {BASE_URL}")
    print(f"  日誌: {logger.run_dir}")
    print(f"{'='*50}\n")

    for p in phases:
        if str(p) in done:
            print(f"  ⏭ Phase {p} 已完成"); continue
        if p not in phase_map: continue
        try:
            t0 = time.time()
            print(f"  ▶ Phase {p}...", flush=True)
            phase_map[p]()
            print(f"  ◀ Phase {p} done ({time.time()-t0:.1f}s)\n", flush=True)
        except KeyboardInterrupt:
            logger.save_checkpoint()
            print(f"\n⚠ 中斷。--resume 繼續"); break
        except Exception as e:
            logger.log_error(f"p{p}", e)
            logger.save_checkpoint()
            print(f"  ❌ Phase {p}: {e}")

    print(f"\n  📝 產生報告...")
    logger.generate_report()
    logger.save_checkpoint()
    print(f"\n{'='*50}")
    print(f"  ✅ 完成！ 報告: {logger.summary_path}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
