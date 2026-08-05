#!/usr/bin/env python
"""
P0-4：Parent Doc / Sibling / Context Fitting Ablation

對照稽核文件 §4.4 驗收：
- Parent section 單元測試：擴展、去重、citation 不丟失
- 跨 chunk 題 Hit@5／answer correctness 提升
- Multi-query on/off paired ablation
- p95 latency 與 token 使用量
- 新 Z5 hold-out，不只重跑 Z4

使用方式：
  python scripts/eval_parent_doc_ablation.py --profile z5_holdout
  python scripts/eval_parent_doc_ablation.py --profile z3_blind --baseline-only

環境變數：
  PARENT_DOC_ENABLED=true/false
  SIBLING_EXPANSION_ENABLED=true/false
  CONTEXT_FITTING_ENABLED=true/false
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = PROJECT_ROOT / "artifacts"


def run_ablation(profile_name: str, baseline_only: bool = False) -> int:
    """執行 Parent Doc / Sibling / Context Fitting ablation。"""
    try:
        from app.eval import load_profile
    except ImportError:
        print("ERROR: cannot import app.eval — run from project root")
        return 1

    profile = load_profile(profile_name)

    if not profile.questions_path.exists():
        print(f"ERROR: questions file not found: {profile.questions_path}")
        print("Z5 題庫尚未建立，請先執行 scripts/build_blind_z5_corpus.py")
        return 1

    # 定義 ablation arms
    arms = [
        {
            "name": "baseline",
            "env": {
                "PARENT_DOC_ENABLED": "false",
                "SIBLING_EXPANSION_ENABLED": "false",
                "CONTEXT_FITTING_ENABLED": "false",
            },
        },
    ]
    if not baseline_only:
        arms.extend([
            {
                "name": "parent_doc",
                "env": {
                    "PARENT_DOC_ENABLED": "true",
                    "SIBLING_EXPANSION_ENABLED": "false",
                    "CONTEXT_FITTING_ENABLED": "false",
                },
            },
            {
                "name": "sibling",
                "env": {
                    "PARENT_DOC_ENABLED": "false",
                    "SIBLING_EXPANSION_ENABLED": "true",
                    "CONTEXT_FITTING_ENABLED": "false",
                },
            },
            {
                "name": "context_fitting",
                "env": {
                    "PARENT_DOC_ENABLED": "false",
                    "SIBLING_EXPANSION_ENABLED": "false",
                    "CONTEXT_FITTING_ENABLED": "true",
                },
            },
            {
                "name": "all_enabled",
                "env": {
                    "PARENT_DOC_ENABLED": "true",
                    "SIBLING_EXPANSION_ENABLED": "true",
                    "CONTEXT_FITTING_ENABLED": "true",
                },
            },
        ])

    results = {}
    for arm in arms:
        arm_name = arm["name"]
        print(f"\n{'='*60}")
        print(f"Running arm: {arm_name}")
        print(f"{'='*60}")

        # 設定環境變數
        for key, val in arm["env"].items():
            os.environ[key] = val

        # 這裡應該呼叫 eval_answer_correctness.py 的邏輯
        # 目前先記錄 arm 設定，實際跑分需 LIVE stack
        t0 = time.time()
        # TODO: 實際跑分時呼叫 eval_answer_correctness.main() 或直接 import
        elapsed = time.time() - t0

        results[arm_name] = {
            "env": arm["env"],
            "elapsed_s": elapsed,
            "profile": profile.to_dict(),
            "note": "skeleton — actual eval requires LIVE stack",
        }

    # 輸出 ablation 結果
    artifact_path = ARTIFACTS / f"parent_doc_ablation_{profile_name}_last_run.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "gate": "parent-doc-ablation",
        "profile": profile.to_dict(),
        "arms": results,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    artifact_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAblation artifact: {artifact_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Parent Doc / Sibling / Context Fitting Ablation")
    ap.add_argument("--profile", default="z5_holdout", help="Eval profile name")
    ap.add_argument("--baseline-only", action="store_true", help="只跑 baseline")
    args = ap.parse_args()
    return run_ablation(args.profile, args.baseline_only)


if __name__ == "__main__":
    raise SystemExit(main())