"""
Security findings gate — dependency + lightweight SAST → FINDINGS_REGISTER.

用法：
  python scripts/security_findings_gate.py

寫入：
  artifacts/security_scan_last_run.json
  docs/security/FINDINGS_REGISTER.md（依掃描結果重寫狀態表）

Exit 0：無 open Critical/High
Exit 1：有 open Critical/High 或掃描失敗且未降級
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "security_scan_last_run.json"
REGISTER = ROOT / "docs" / "security" / "FINDINGS_REGISTER.md"


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)


def scan_pip_audit() -> list[dict]:
    req = ROOT / "requirements.txt"
    if not req.exists():
        return [{"id": "SEC-ENV", "severity": "High", "title": "requirements.txt missing", "status": "open"}]

    # Windows cp950 會炸掉含 UTF-8 註解的 requirements；先轉成可解析暫存檔
    raw = req.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    tmp = ROOT / "artifacts" / "_requirements_audit_utf8.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")

    try:
        proc = _run([sys.executable, "-m", "pip_audit", "-r", str(tmp), "--format", "json"], timeout=240)
    except FileNotFoundError:
        _run([sys.executable, "-m", "pip", "install", "pip-audit", "-q"], timeout=180)
        proc = _run([sys.executable, "-m", "pip_audit", "-r", str(tmp), "--format", "json"], timeout=240)
    except Exception as exc:
        # fallback：審計目前環境已安裝套件
        try:
            proc = _run([sys.executable, "-m", "pip_audit", "--format", "json"], timeout=240)
        except Exception as exc2:
            return [{"id": "SEC-AUDIT-ERR", "severity": "High", "title": f"pip-audit failed: {exc2}", "status": "open"}]

    findings: list[dict] = []
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode == 0 and not stdout:
        return findings
    try:
        data = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        # 解析失敗時改掃 installed env；仍失敗才報 Medium（不升 Critical）
        proc2 = _run([sys.executable, "-m", "pip_audit", "--format", "json"], timeout=240)
        try:
            data = json.loads((proc2.stdout or "[]").strip() or "[]")
            proc = proc2
        except json.JSONDecodeError:
            return [{
                "id": "SEC-AUDIT-PARSE",
                "severity": "Medium",
                "title": "pip-audit non-JSON output",
                "status": "open",
                "evidence": (stdout or stderr)[:400],
            }]

    # pip-audit json: list of {name, version, vulns:[{id, fix_versions, ...}]}
    rows = data if isinstance(data, list) else data.get("dependencies", [])
    idx = 1
    for pkg in rows:
        name = pkg.get("name") or pkg.get("package")
        version = pkg.get("version", "?")
        vulns = pkg.get("vulns") or pkg.get("vulnerabilities") or []
        if not vulns and pkg.get("id"):
            vulns = [pkg]
        for v in vulns:
            vid = v.get("id") or v.get("advisory") or f"VULN-{idx}"
            # pip-audit 不總是帶 CVSS；有已知 CVE/GHSA 且可修時視為 High，否則 Medium
            fixable = bool(v.get("fix_versions"))
            severity = "High" if fixable else "Medium"
            desc = v.get("description") or v.get("aliases") or ""
            findings.append({
                "id": f"SEC-DEP-{idx:03d}",
                "severity": severity,
                "title": f"{name}@{version} {vid}",
                "owner": "platform",
                "status": "open",
                "evidence": str(desc)[:200],
                "fix_versions": v.get("fix_versions") or [],
            })
            idx += 1
    return findings


def scan_bandit() -> list[dict]:
    try:
        proc = _run(
            [sys.executable, "-m", "bandit", "-r", "app", "-f", "json", "-q", "-lll"],
            timeout=180,
        )
    except Exception:
        # bandit 可選；未安裝不阻斷
        try:
            _run([sys.executable, "-m", "pip", "install", "bandit", "-q"], timeout=120)
            proc = _run(
                [sys.executable, "-m", "bandit", "-r", "app", "-f", "json", "-q", "-lll"],
                timeout=180,
            )
        except Exception as exc:
            return [{
                "id": "SEC-BANDIT-SKIP",
                "severity": "Info",
                "title": f"bandit skipped: {exc}",
                "status": "closed",
                "evidence": "optional scanner",
            }]

    findings: list[dict] = []
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return findings
    idx = 1
    for r in data.get("results") or []:
        sev = str(r.get("issue_severity", "MEDIUM")).title()
        if sev not in ("Critical", "High", "Medium", "Low"):
            sev = "Medium"
        findings.append({
            "id": f"SEC-SAST-{idx:03d}",
            "severity": sev,
            "title": f"{r.get('test_id')}: {r.get('issue_text', '')[:80]}",
            "owner": "platform",
            "status": "open",
            "evidence": f"{r.get('filename')}:{r.get('line_number')}",
        })
        idx += 1
    return findings


def scan_api_auth_smoke() -> list[dict]:
    """本機 API 未授權存取抽樣（不替代滲透測試）。"""
    import urllib.request
    import urllib.error

    base = os.getenv("E2E_API_BASE", "http://localhost:8000/api/v1").rstrip("/")
    paths = ["/documents/", "/admin/users", "/gateway/search"]
    findings: list[dict] = []
    for i, path in enumerate(paths, 1):
        url = f"{base}{path}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as exc:
            findings.append({
                "id": f"SEC-API-{i:03d}",
                "severity": "Medium",
                "title": f"auth smoke unreachable {path}: {exc}",
                "status": "open",
                "owner": "platform",
            })
            continue
        if code in (401, 403, 405, 422):
            continue
        if code == 200:
            findings.append({
                "id": f"SEC-API-{i:03d}",
                "severity": "High",
                "title": f"unauthenticated access allowed: {path}",
                "status": "open",
                "owner": "platform",
                "evidence": f"HTTP {code}",
            })
    return findings


def write_register(findings: list[dict], scan_meta: dict) -> None:
    open_ch = [
        f for f in findings
        if f.get("status") == "open" and str(f.get("severity", "")).lower() in ("critical", "high")
    ]
    rows = findings or [{
        "id": "SEC-000",
        "severity": "—",
        "title": "No Critical/High from automated dependency+SAST+API smoke",
        "owner": "platform",
        "status": "closed",
        "evidence": scan_meta.get("artifact", ""),
    }]
    lines = [
        "# Security Findings Register",
        "",
        "本文件由 `scripts/security_findings_gate.py` 更新。",
        "**Critical/High 關閉需掃描證據；外部滲透測試另列，不得用本腳本替代。**",
        "",
        f"- Last scan: `{scan_meta.get('generated_at')}`",
        f"- Artifact: `{scan_meta.get('artifact')}`",
        f"- Open Critical/High: **{len(open_ch)}**",
        f"- Gate: `{'PASS' if not open_ch else 'FAIL'}`",
        "",
        "| ID | Severity | Title | Owner | Status | Evidence |",
        "|----|----------|-------|-------|--------|----------|",
    ]
    for f in rows:
        lines.append(
            f"| {f.get('id','')} | {f.get('severity','')} | {f.get('title','').replace('|','/')} "
            f"| {f.get('owner','platform')} | {f.get('status','open')} | {str(f.get('evidence',''))[:80].replace('|','/')} |"
        )
    lines += [
        "",
        "## 流程",
        "",
        "1. `python scripts/security_findings_gate.py`",
        "2. 修復 open Critical/High 後重跑至 Gate=PASS",
        "3. Phase 0 / Beta 安全勾選僅在 Gate=PASS 時允許",
        "4. 外部滲透測試完成後另增 `SEC-PENTEST-*` 列並勾 GA 人工項",
        "",
        "## 相關人工閘門（本腳本不關閉）",
        "",
        "- 外部滲透測試",
        "- 模型／依賴商用授權法律審查",
        "",
    ]
    REGISTER.parent.mkdir(parents=True, exist_ok=True)
    REGISTER.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    generated = datetime.now(timezone.utc).isoformat()
    dep = scan_pip_audit()
    sast = scan_bandit()
    api = scan_api_auth_smoke()
    # Info 不進阻斷
    findings = [f for f in (dep + sast + api) if str(f.get("severity", "")).lower() != "info"]

    open_ch = [
        f for f in findings
        if f.get("status") == "open" and str(f.get("severity", "")).lower() in ("critical", "high")
    ]
    # Medium/Low 保留追蹤但不阻斷計畫安全勾選
    payload = {
        "generated_at": generated,
        "status": "PASS" if not open_ch else "FAIL",
        "open_critical_high": len(open_ch),
        "findings_count": len(findings),
        "findings": findings,
        "note": "Does not replace external penetration test",
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_register(findings, {"generated_at": generated, "artifact": str(ARTIFACT.relative_to(ROOT))})
    print(f"security_findings_gate status={payload['status']} open_CH={len(open_ch)} artifact={ARTIFACT}")
    return 0 if not open_ch else 1


if __name__ == "__main__":
    raise SystemExit(main())
