"""盤點所有 completed 文件的 chunk 文本總量 vs 檔案大小，校準 thin delivery 閾值。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5435, dbname="enclave", user="postgres", password="postgres"
)
cur = conn.cursor()
cur.execute(
    """
    SELECT d.filename, d.file_size, d.file_type,
           d.quality_report->>'parse_route' AS route,
           count(c.id) AS chunks,
           coalesce(sum(length(c.text)), 0) AS total_chars
    FROM documents d
    LEFT JOIN documentchunks c ON c.document_id = d.id
    WHERE d.status = 'completed' AND d.tombstoned_at IS NULL
    GROUP BY d.id, d.filename, d.file_size, d.file_type, route
    ORDER BY total_chars ASC
    """
)
rows = cur.fetchall()
print(f"completed docs: {len(rows)}")
print(f"{'chars':>7} {'chunks':>6} {'size KB':>8} {'type':>5} {'route':>18}  filename")
for fn, size, ftype, route, chunks, chars in rows:
    flag = " <<< THIN?" if (size or 0) > 100_000 and chars < 1500 else ""
    print(f"{chars:>7} {chunks:>6} {(size or 0)//1024:>8} {ftype:>5} {str(route):>18}  {fn}{flag}")
