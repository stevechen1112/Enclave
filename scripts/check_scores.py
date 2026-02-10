import json
import sys

log_path = "/code/test-data/test-results/run_20260211_031503/test_log.jsonl"
targets = {"A2", "C4", "E1", "E3", "H1"}

with open(log_path) as f:
    for line in f:
        d = json.loads(line)
        qid = d.get("qid", "")
        if qid in targets:
            ans = d.get("answer", "")
            src = d.get("sources", [])
            print(f"===== {qid} =====")
            print(f"answer_len: {len(ans)}")
            print(f"sources_count: {len(src)}")
            print(f"score: {d.get('score')}/{d.get('max_score')}")
            print(f"answer: {ans[:300]}")
            print()
