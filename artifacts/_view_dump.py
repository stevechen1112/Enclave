import json, sys

d = json.load(open("artifacts/_golden_ocr_dump.json", encoding="utf-8"))
keys = sys.argv[1:] or list(d.keys())
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 6000
keys = [k for k in keys if not k.startswith("--") and k != str(limit)]
with open("artifacts/_view_out.txt", "w", encoding="utf-8") as f:
    for k in keys:
        f.write("######## %s %s\n" % (k, d[k]["filename"]))
        f.write(d[k]["text"][:limit])
        f.write("\n\n")
print("ok")
