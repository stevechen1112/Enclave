import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
)
cur = conn.cursor()
cur.execute(
    """
    SELECT d.filename, c.text FROM documentchunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.created_at > now() - interval '3 hours'
    """
)
by_doc = {}
for fn, txt in cur.fetchall():
    by_doc.setdefault(fn, "")
    by_doc[fn] += (txt or "") + "\n"

SPANS = {
    "113年營所稅申報書_E42八策.pdf": ["113", "八策數位", "83028948"],
    "1140213-拉法(存奕官網)_報價單.docx": ["9,600", "玉山銀行", "療程頁", "新知頁"],
    "吳文曄-履歷.pdf": ["靜宜", "碩士", "營養師", "研發營養師"],
    "巨大機械9921深度研究報告.pdf": ["CADEX", "審慎觀察", "36%", "Momentum"],
    "亞馬遜行銷報價.pdf": ["Awareness", "Acquisition", "Purchase", "Retention"],
    "臺北市產業發展獎勵補助計畫申請簡介.pdf": ["500萬", "200萬", "5000萬", "300萬"],
    "基礎操作教學手冊.pdf": ["portal.nueip.com", "Google", "Facebook"],
    "【將能數位行銷】-巽耘法律事務所-健診報告.pdf": ["69", "尚未提交"],
}
for fn, spans in SPANS.items():
    text = by_doc.get(fn, "")
    print(f"== {fn} ({len(text)} chars)")
    for s in spans:
        print("  ", "OK  " if s in text else "MISS", s)
