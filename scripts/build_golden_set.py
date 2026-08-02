"""Z0-2: select a stratified golden corpus from artifacts/corpus_inventory.json.

Copies the selected documents into testdata/golden/files/ and writes a manifest
carrying corpus_snapshot_id, provenance and a sensitivity flag per document.

Sensitivity: paths under customer/client folders are flagged. They are EXCLUDED by
default; pass --include-sensitive only for locally-executed parsing evaluation, and
never for evaluations that send content to a cloud LLM.

Usage:
  python scripts/build_golden_set.py                 # safe default
  python scripts/build_golden_set.py --include-sensitive
"""
import argparse
import hashlib
import json
import pathlib
import random
import shutil
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "artifacts" / "corpus_inventory.json"
GOLDEN = ROOT / "testdata" / "golden"
FILES = GOLDEN / "files"
MANIFEST = GOLDEN / "manifest.json"

# Directory names that suggest real customer / client material.
SENSITIVE_MARKERS = ("客戶", "八策", "aihr", "漢本", "鳳凰顧問", "CYS")

# Filename hints used to spread the textual sample across document genres.
GENRE_HINTS = {
    "laws": ("規則", "辦法", "條例", "法規", "章程", "規章", "準則"),
    "manual": ("手冊", "說明書", "操作", "指南", "作業", "流程", "SOP"),
    "report": ("報告", "報告書", "年報", "永續", "財報"),
    "contract": ("契約", "合約", "協議", "標單", "投標"),
    "form": ("表單", "申請", "簽呈", "公文", "函"),
}

TARGETS = {
    "scanned_1_5": 12,
    "scanned_6_20": 10,
    "scanned_21_60": 8,
    "scanned_61plus": 4,
    "textual": 24,
    "office": 12,
}


def page_bucket(pages: int) -> str:
    if pages <= 5:
        return "scanned_1_5"
    if pages <= 20:
        return "scanned_6_20"
    if pages <= 60:
        return "scanned_21_60"
    return "scanned_61plus"


def genre_of(path: str) -> str:
    name = pathlib.Path(path).name
    for genre, hints in GENRE_HINTS.items():
        if any(h in name for h in hints):
            return genre
    return "other"


def is_sensitive(path: str) -> bool:
    return any(m in path for m in SENSITIVE_MARKERS)


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pick(pool: list, n: int, rng: random.Random) -> list:
    """Take n items, spreading across genres before falling back to random fill."""
    by_genre: dict[str, list] = {}
    for e in pool:
        by_genre.setdefault(genre_of(e["path"]), []).append(e)
    for items in by_genre.values():
        rng.shuffle(items)

    chosen, genres = [], sorted(by_genre)
    while len(chosen) < n and any(by_genre[g] for g in genres):
        for g in genres:
            if len(chosen) >= n:
                break
            if by_genre[g]:
                chosen.append(by_genre[g].pop())
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-sensitive", action="store_true")
    ap.add_argument("--seed", type=int, default=20260802)
    args = ap.parse_args()

    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    docs = inv["documents"]
    rng = random.Random(args.seed)

    usable = [e for e in docs if args.include_sensitive or not is_sensitive(e["path"])]
    excluded_sensitive = len(docs) - len(usable)

    scanned = [e for e in usable if e.get("kind") == "scanned"]
    textual = [e for e in usable if e.get("kind") == "textual"]
    office = [e for e in usable if e["ext"] != ".pdf"]

    selection: list[dict] = []
    for bucket in ("scanned_1_5", "scanned_6_20", "scanned_21_60", "scanned_61plus"):
        pool = [e for e in scanned if page_bucket(e.get("pages", 0)) == bucket]
        for e in pick(pool, TARGETS[bucket], rng):
            selection.append({**e, "stratum": bucket})
    for e in pick(textual, TARGETS["textual"], rng):
        selection.append({**e, "stratum": "textual"})
    for e in pick(office, TARGETS["office"], rng):
        selection.append({**e, "stratum": "office"})

    if FILES.exists():
        shutil.rmtree(FILES)
    FILES.mkdir(parents=True, exist_ok=True)

    entries, failures = [], []
    for idx, e in enumerate(selection):
        src = pathlib.Path(e["path"])
        if not src.exists():
            failures.append(e["path"])
            continue
        dest = FILES / f"{idx:03d}_{src.name}"
        try:
            shutil.copy2(src, dest)
        except OSError as err:
            failures.append(f"{e['path']} ({type(err).__name__})")
            continue
        entries.append({
            "id": f"{idx:03d}",
            "file": dest.name,
            "stratum": e["stratum"],
            "genre": genre_of(e["path"]),
            "ext": e["ext"],
            "size": e["size"],
            "pages": e.get("pages"),
            "chars_per_page": e.get("chars_per_page"),
            "kind": e.get("kind"),
            "sha256": sha256_of(dest),
            "source_path": e["path"],
            "sensitive": is_sensitive(e["path"]),
        })

    snapshot = hashlib.sha256("".join(sorted(x["sha256"] for x in entries)).encode()).hexdigest()[:16]
    manifest = {
        "corpus_snapshot_id": snapshot,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": args.seed,
        "include_sensitive": args.include_sensitive,
        "excluded_sensitive_documents": excluded_sensitive,
        "inventory_generated_at": inv["summary"]["generated_at"],
        "counts": {
            "total": len(entries),
            "scanned": sum(1 for x in entries if x["kind"] == "scanned"),
            "textual": sum(1 for x in entries if x["kind"] == "textual"),
            "office": sum(1 for x in entries if x["ext"] != ".pdf"),
            "sensitive": sum(1 for x in entries if x["sensitive"]),
        },
        "copy_failures": failures,
        "documents": entries,
    }
    GOLDEN.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(manifest["counts"], ensure_ascii=False))
    print(f"corpus_snapshot_id = {snapshot}")
    print(f"excluded sensitive documents from pool = {excluded_sensitive}")
    if failures:
        print(f"copy failures = {len(failures)}")
    print(f"written: {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
