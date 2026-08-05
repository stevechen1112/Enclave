import io, sys, json, glob, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import yaml

dump = json.load(open("artifacts/_golden_ocr_dump.json", encoding="utf-8"))

def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).casefold()
    return "".join(ch for ch in s if not ch.isspace() and ch not in "-–—_:：/()（）")

report = {}
for f in sorted(glob.glob("testdata/golden/z1_scan_annotations/scan_*.yaml")):
    a = yaml.safe_load(open(f, encoding="utf-8"))
    sid = a["id"]
    text = norm(dump[sid]["text"])
    rows = []
    for fld in a.get("fields") or []:
        exp = str(fld["expected"])
        rows.append((fld["name"], exp, norm(exp) in text))
    report[sid] = rows

bad = 0
for sid, rows in report.items():
    print("====", sid, dump[sid]["filename"])
    for name, exp, ok in rows:
        if not ok:
            bad += 1
        print(("  OK " if ok else "  MISS"), name, "=", exp)
print("\nTOTAL MISS:", bad)
