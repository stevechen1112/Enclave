import io, sys, json, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import yaml

dump = json.load(open("artifacts/_golden_ocr_dump.json", encoding="utf-8"))

def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).casefold()
    return "".join(ch for ch in s if not ch.isspace() and ch not in "-–—_:：/()（）")

qs = yaml.safe_load(open("testdata/golden/z1_retrieve_questions.yaml", encoding="utf-8"))
qs = qs if isinstance(qs, list) else qs.get("questions", [])
alltext = norm(" ".join(v["text"] for v in dump.values()))
suspect = 0
for q in qs:
    exp = q.get("expected") or {}
    spans = exp.get("span_contains") or []
    doc_ids = exp.get("document_ids") or []
    for sp in spans:
        in_docs = any(norm(sp) in norm(dump[d]["text"]) for d in doc_ids if d in dump)
        in_any = norm(sp) in alltext
        if not in_any:
            suspect += 1
            print("HALLUCINATION-RISK", q["id"], "| span not in ANY doc:", sp, "| q:", q["query"][:40])
        elif doc_ids and not in_docs:
            print("CROSS-DOC", q["id"], "| span only in other docs:", sp, "| q:", q["query"][:40])
print("\nsuspect spans:", suspect)
