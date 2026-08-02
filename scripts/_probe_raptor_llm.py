"""Minimal RAPTOR LLM wiring probe (1 PDF, throwaway dataset).

Succeeds only if POST .../index?type=raptor does not immediately hit
progress=-1 with Instance*not found. Does not claim retrieval value.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from eval_coverage import api, upload, EMBEDDING_MODEL  # noqa: E402

OUT = ROOT / "artifacts" / "raptor_llm_probe_last_run.json"


def main() -> int:
    src = next((ROOT / "testdata").rglob("*.pdf"))
    created = api("POST", "/api/v1/datasets", {
        "name": f"raptor-llm-probe-{int(time.time())}",
        "embedding_model": EMBEDDING_MODEL,
        "chunk_method": "naive",
        "parser_config": {
            "layout_recognize": "DeepDOC",
            "raptor": {"use_raptor": True},
        },
    })
    ds = (created.get("data") or [{}])[0].get("id") if isinstance(created.get("data"), list) else (created.get("data") or {}).get("id")
    if not ds:
        # RAGFlow sometimes returns data as list
        data = created.get("data")
        if isinstance(data, list) and data:
            ds = data[0].get("id")
    report = {"dataset_id": ds, "create": created, "source": str(src)}
    if not ds:
        report["status"] = "BLOCKED"
        report["reason"] = "dataset_create_failed"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    upload(ds, src)
    # wait parse briefly
    t0 = time.time()
    while time.time() - t0 < 600:
        listed = api("GET", f"/api/v1/datasets/{ds}/documents?page=1&page_size=20")
        docs = ((listed.get("data") or {}).get("docs") or [])
        if docs and all(d.get("run") in ("DONE", "FAIL", "CANCEL") for d in docs):
            break
        time.sleep(10)
        print(f"  parse wait {time.time()-t0:.0f}s", flush=True)

    trigger = api("POST", f"/api/v1/datasets/{ds}/index?type=raptor", {})
    report["trigger"] = trigger
    # poll a few times
    progress = None
    msg = ""
    for _ in range(12):
        time.sleep(5)
        st = api("GET", f"/api/v1/datasets/{ds}/index?type=raptor")
        data = st.get("data") or {}
        progress = data.get("progress") if isinstance(data, dict) else None
        msg = str(data.get("progress_msg") or data or st)[:300]
        print(f"  progress={progress!r} msg={msg[:120]}", flush=True)
        if progress == -1 or progress == 1 or progress == 1.0:
            break

    report["progress"] = progress
    report["progress_msg"] = msg
    if progress == -1 and "Instance" in msg:
        report["status"] = "FAIL"
        report["reason"] = "llm_instance_still_broken"
    elif progress == -1:
        report["status"] = "FAIL"
        report["reason"] = "raptor_progress_negative"
    elif progress in (1, 1.0):
        report["status"] = "PASS"
        report["reason"] = "raptor_index_completed"
    else:
        report["status"] = "INCONCLUSIVE"
        report["reason"] = f"progress={progress}"

    try:
        api("DELETE", f"/api/v1/datasets?ids={ds}")
    except Exception:
        pass

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
