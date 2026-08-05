"""離線重評分：用最新 span 正規化重判既有 artifact，不需重跑 LLM。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "scripts")
from eval_answer_correctness import span_in_answer

for name in sys.argv[1:]:
    d = json.load(open(f"artifacts/answer_correctness_{name}.json", encoding="utf-8"))
    npass = nfail = nreview = 0
    fails = []
    for r in d["results"]:
        if r.get("verdict") == "review":
            nreview += 1
            continue
        spans = r.get("spans_expected") or []
        ok = all(span_in_answer(s, r["answer"]) for s in spans)
        if ok:
            npass += 1
        else:
            nfail += 1
            fails.append(r["id"])
    total = npass + nfail + nreview
    print(f"{name}: {npass}/{total} pass ({npass/total*100:.1f}%) fail={fails}")
