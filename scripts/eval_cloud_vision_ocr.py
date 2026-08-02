"""CV-RF-01b cloud multimodal OCR ablation arm (multi-provider).

Same 12 annotated real scans, same 66 fields, same scoring as
eval_parse_ablation.py (score_arm / best_window_cer, strict + t2s).
Each PDF page is rasterized (200 DPI) and transcribed by a cloud vision
model; compared against the DeepDOC arm in parse_ablation_last_run.json.

Usage:
  python scripts/eval_cloud_vision_ocr.py --provider openai --model gpt-5.6-terra \
      --out artifacts/cloud_vision_terra_ablation_last_run.json
  python scripts/eval_cloud_vision_ocr.py --provider gemini --model gemini-3-flash-preview \
      --out artifacts/cloud_vision_gemini_ablation_last_run.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import time

import fitz  # PyMuPDF
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app.eval import judge  # noqa: E402
from eval_parse_ablation import load_annotations, score_arm  # noqa: E402

BASELINE_ARTIFACT = ROOT / "artifacts" / "parse_ablation_last_run.json"
DPI = 200

PROMPT = (
    "這是一份掃描文件的其中一頁影像。請逐字轉錄頁面上的所有文字，"
    "保留原始繁體中文（不要轉成簡體）、數字、日期與表格內容。"
    "只輸出轉錄文字，不要加任何說明或格式標記。"
)


def _load_env():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def transcribe_openai(client: httpx.Client, model: str, png: bytes) -> str:
    b64 = base64.b64encode(png).decode()
    r = client.post("/chat/completions", json={
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_completion_tokens": 4096,
    })
    if r.status_code != 200:
        raise RuntimeError(f"http_{r.status_code}: {r.text[:200]}")
    data = r.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def transcribe_gemini(client: httpx.Client, model: str, png: bytes) -> str:
    b64 = base64.b64encode(png).decode()
    r = client.post(f"/v1beta/models/{model}:generateContent", json={
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/png", "data": b64}},
        ]}],
        "generationConfig": {"maxOutputTokens": 8192},
    })
    if r.status_code != 200:
        raise RuntimeError(f"http_{r.status_code}: {r.text[:200]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"no_candidates: {json.dumps(data)[:200]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


def transcribe_mistral(client: httpx.Client, model: str, png: bytes) -> tuple[str, dict]:
    b64 = base64.b64encode(png).decode()
    r = client.post("/v1/ocr", json={
        "model": model,
        "document": {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"},
    })
    if r.status_code != 200:
        raise RuntimeError(f"http_{r.status_code}: {r.text[:200]}")
    data = r.json()
    page = (data.get("pages") or [{}])[0]
    return page.get("markdown") or "", page.get("confidence_scores") or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["openai", "gemini", "mistral"], default="openai")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "cloud_vision_ocr_ablation_last_run.json"))
    args = ap.parse_args()

    _load_env()
    docs = load_annotations()
    if not docs:
        print("no annotated documents found")
        return 1
    total_fields = sum(len(d["fields"]) for d in docs)
    print(f"provider={args.provider} model={args.model} docs={len(docs)} fields={total_fields}")

    if args.provider == "openai":
        client = httpx.Client(base_url="https://api.openai.com/v1",
                              headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                              timeout=180.0)
        transcribe = transcribe_openai
    elif args.provider == "gemini":
        client = httpx.Client(base_url="https://generativelanguage.googleapis.com",
                              headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                              timeout=180.0)
        transcribe = transcribe_gemini
    else:
        client = httpx.Client(base_url="https://api.mistral.ai",
                              headers={"Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}"},
                              timeout=180.0)
        transcribe = transcribe_mistral

    t0 = time.time()
    per_doc: dict[str, dict] = {}
    confidences: list[dict] = []
    errors = []
    retries = 0

    for doc in docs:
        texts = []
        pdf = fitz.open(doc["path"])
        for page in pdf:
            png = page.get_pixmap(dpi=DPI).tobytes("png")
            out = ""
            for attempt in range(3):
                try:
                    result = transcribe(client, args.model, png)
                    if args.provider == "mistral":
                        out, conf = result
                        if conf:
                            confidences.append({"doc": doc["id"], "page": page.number, **conf})
                    else:
                        out = result
                    if out.strip():
                        break
                    retries += 1  # silent empty response -> retry
                except Exception as exc:
                    retries += 1
                    if attempt == 2:
                        errors.append({"doc": doc["id"], "page": page.number,
                                       "error": str(exc)[:200]})
                time.sleep(2)
            texts.append(out)
        per_doc[doc["id"]] = {"text": "\n".join(texts)}
        print(f"  {doc['id']}: {len(pdf)} pages, {len(per_doc[doc['id']]['text'])} chars",
              flush=True)
        pdf.close()
    client.close()

    elapsed = round(time.time() - t0, 1)
    scored = score_arm(per_doc, docs)

    base = json.loads(BASELINE_ARTIFACT.read_text(encoding="utf-8"))
    deepdoc = base["summary"]["DeepDOC"]
    plaintext = base["summary"]["Plain Text"]

    dd_field_hits = [r["hit"] for r in base["per_field"]["DeepDOC"]]
    cv_field_hits = [r["hit"] for r in scored["per_field"]]
    only_dd = sum(1 for a, b in zip(dd_field_hits, cv_field_hits) if a and not b)
    only_cv = sum(1 for a, b in zip(dd_field_hits, cv_field_hits) if b and not a)
    verdict = judge(deepdoc["hits"], scored["hits"], total_fields,
                    threshold=0.20, discordant=(only_dd, only_cv))

    report = {
        "gate": "CV-RF-01b-cloud-arm",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus": "real_scan_annotated",
        "golden_tier": 1,
        "provider": args.provider,
        "model_used": args.model,
        "dpi": DPI,
        "n_docs": len(docs),
        "n_fields": total_fields,
        "elapsed_s": elapsed,
        "retries": retries,
        "errors": errors,
        "confidence_scores": confidences,
        "summary": {
            "Plain Text": {"hit_rate": plaintext["hit_rate"], "mean_cer": plaintext["mean_cer"]},
            "DeepDOC": {"hit_rate": deepdoc["hit_rate"], "mean_cer": deepdoc["mean_cer"]},
            "CloudVision": {
                "hits": scored["hits"], "fields": scored["fields"],
                "hit_rate": scored["hit_rate"], "mean_cer": scored["mean_cer"],
                "hit_rate_strict": scored["hit_rate_strict"],
                "mean_cer_strict": scored["mean_cer_strict"],
                "elapsed_s": elapsed,
            },
        },
        "cloud_vs_deepdoc_judgement": verdict.as_dict(),
        "per_field": scored["per_field"],
        "note": "Same annotations/scoring as CV-RF-01b; judgement pairs CloudVision vs DeepDOC.",
    }
    out_path = pathlib.Path(args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== RESULT =====")
    print(f"  Plain Text   hit={plaintext['hit_rate']:.1%} cer={plaintext['mean_cer']}")
    print(f"  DeepDOC      hit={deepdoc['hit_rate']:.1%} cer={deepdoc['mean_cer']}")
    print(f"  CloudVision  hit={scored['hit_rate']:.1%} ({scored['hits']}/{scored['fields']}) "
          f"cer={scored['mean_cer']} | strict hit={scored['hit_rate_strict']:.1%} "
          f"cer={scored['mean_cer_strict']} | model={args.model} elapsed={elapsed}s "
          f"retries={retries} errors={len(errors)}")
    print(f"  vs DeepDOC judgement = {verdict.judgement} (delta={verdict.delta:+.1%}, "
          f"CI low={verdict.ci_low:+.3f})")
    print(f"written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
