"""Build Blind Z3 dual-root corpus (八策 + 客戶).

Authoring-safe: writes only path metadata (no text extraction).
Rules: exclude Z2 filenames, dedupe by (name, size), stratify, cap near-dupes.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOTS = {
    "八策": Path(r"C:\Users\User\Desktop\八策"),
    "客戶": Path(r"C:\Users\User\Desktop\客戶"),
}
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3"

Z2_USED = [
    "113年營所稅",
    "拉法",
    "吳文曄",
    "巨大機械",
    "亞馬遜行銷報價",
    "臺北市產業發展",
    "基礎操作教學手冊",
    "巽耘法律事務所-健診",
]

# Prefer business-document signals in filename
STRATA = {
    "contract": re.compile(r"(合約|協議|委任|委託合約)"),
    "quote": re.compile(r"(報價)"),
    "proposal": re.compile(r"(提案|企劃)"),
    "gov": re.compile(r"(補助|請款|投保|勞保|切結|發票|營業登記|辦公室合約|續約)"),
    "spec": re.compile(r"(規格|手冊|SOP)"),
}
SKIP = re.compile(
    r"(報表|投放報告|廣告數據|粉絲團流量|logo|完稿|大頭照|"
    r"要注意什麼|是什麼？|怎麼辦|教學|簡報提案術|Registration_Guidebook|"
    r"projects-and-references|Marketing Proposal|OpenHouse|品牌行銷策略建議)",
    re.I,
)
MIN_B, MAX_B = 25 * 1024, 12 * 1024 * 1024


def stratum(name: str) -> str:
    for k, rx in STRATA.items():
        if rx.search(name):
            return k
    return "other"


def norm_name(name: str) -> str:
    n = name.lower()
    n = re.sub(r"[\s_\-（）()【】\[\]]+", "", n)
    n = re.sub(r"(signed|用印|final|調整版|\d{8}|\d{6})", "", n)
    return n


def main() -> None:
    cands: list[dict] = []
    seen_key: set[tuple[str, int]] = set()

    for root_id, root in ROOTS.items():
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".pdf", ".docx"}:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if not (MIN_B <= size <= MAX_B):
                continue
            name = p.name
            if any(u in name for u in Z2_USED):
                continue
            if SKIP.search(name) or SKIP.search(str(p)):
                continue
            rel = p.relative_to(root).as_posix()
            top = rel.split("/", 1)[0]
            # skip mistaking file-at-root as deep client only for 客戶 diversity
            client = top if not top.lower().endswith((".pdf", ".docx")) else "(root)"
            key = (norm_name(name), size)
            if key in seen_key:
                continue
            seen_key.add(key)
            cands.append(
                {
                    "root": root_id,
                    "path": str(p),
                    "rel": rel,
                    "client": client,
                    "name": name,
                    "ext": p.suffix.lower(),
                    "bytes": size,
                    "stratum": stratum(name),
                }
            )

    # Per (root, client, stratum) keep largest 1; allow 2 for quote/contract to enable type-E
    by_bucket: dict[tuple, list] = defaultdict(list)
    for c in sorted(cands, key=lambda x: -x["bytes"]):
        lim = 2 if c["stratum"] in {"quote", "contract", "proposal"} else 1
        key = (c["root"], c["client"], c["stratum"])
        if len(by_bucket[key]) < lim:
            # near-dup name guard within bucket
            nn = norm_name(c["name"])
            if any(norm_name(x["name"]) == nn for x in by_bucket[key]):
                continue
            by_bucket[key].append(c)

    pool = [x for items in by_bucket.values() for x in items]

    # Target mix (~55): prefer contract/quote/gov/proposal; pull from both roots
    selected: list[dict] = []
    quotas = {
        ("客戶", "contract"): 12,
        ("客戶", "quote"): 12,
        ("客戶", "proposal"): 8,
        ("八策", "contract"): 6,
        ("八策", "gov"): 6,
        ("八策", "quote"): 4,
        ("客戶", "spec"): 2,
        ("八策", "proposal"): 2,
    }

    used_paths: set[str] = set()
    for (root, st), q in quotas.items():
        bucket = [c for c in pool if c["root"] == root and c["stratum"] == st and c["path"] not in used_paths]
        # diversify clients
        picked = []
        seen_client: set[str] = set()
        for c in sorted(bucket, key=lambda x: -x["bytes"]):
            if c["client"] in seen_client and len(picked) >= max(1, q // 2):
                # allow second file from same client only after others filled
                continue
            picked.append(c)
            seen_client.add(c["client"])
            used_paths.add(c["path"])
            if len(picked) >= q:
                break
        # fill remainder without client lock
        if len(picked) < q:
            for c in sorted(bucket, key=lambda x: -x["bytes"]):
                if c["path"] in used_paths:
                    continue
                picked.append(c)
                used_paths.add(c["path"])
                if len(picked) >= q:
                    break
        selected.extend(picked)

    # If under target, top up with unused pool — prefer contract/quote/gov only
    if len(selected) < 50:
        seen_c = {c["client"] for c in selected}
        prefer = [c for c in pool if c["stratum"] in {"contract", "quote", "gov", "proposal", "spec"}]
        for c in sorted(prefer, key=lambda x: -x["bytes"]):
            if c["path"] in used_paths:
                continue
            if c["client"] in seen_c and len(selected) >= 45:
                continue
            selected.append(c)
            used_paths.add(c["path"])
            seen_c.add(c["client"])
            if len(selected) >= 55:
                break

    selected = selected[:55]

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_roots": {k: str(v) for k, v in ROOTS.items()},
        "count": len(selected),
        "note": (
            "Dual-root hold-out; metadata only for authoring; "
            "do not commit raw files; Z2 filenames excluded; deduped by name+size"
        ),
        "strata": {k: sum(1 for s in selected if s["stratum"] == k) for k in STRATA},
        "by_root": {
            "八策": sum(1 for s in selected if s["root"] == "八策"),
            "客戶": sum(1 for s in selected if s["root"] == "客戶"),
        },
        "files": selected,
    }
    manifest = OUT / "corpus_manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Authoring catalog: no paths to extracts
    catalog = {
        "rule": "Write intents from client+name+stratum only. Do NOT open file contents or extracts/.",
        "files": [
            {
                "id": f"doc-{i:02d}",
                "root": f["root"],
                "client": f["client"],
                "name": f["name"],
                "stratum": f["stratum"],
                "ext": f["ext"],
                "rel": f["rel"],
            }
            for i, f in enumerate(selected, 1)
        ],
    }
    (OUT / "authoring_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"CANDS={len(cands)} POOL={len(pool)} SELECTED={len(selected)}")
    print("by_root", payload["by_root"], "strata", payload["strata"])
    for s in selected:
        print(f"{s['root']}\t{s['stratum']}\t{s['client']}\t{s['bytes']//1024}KB\t{s['name']}")
    print(f"WROTE {manifest}")
    print(f"WROTE {OUT / 'authoring_catalog.json'}")


if __name__ == "__main__":
    main()
