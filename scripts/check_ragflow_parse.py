"""Check RAGFlow parse status."""
import httpx, re

TOKEN = 'IjI0NDQxMzg2OGQwNTExZjE5ODc2ZDE4Njc2ZmE3MTYzIg.amzbIA.eUaE3lFOQ8-3HwK-l7nSnHx2R6k'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}
DATASET_ID = '599692668d0511f199eeb37ca37a0366'

r = httpx.get(f'http://localhost:9380/api/v1/datasets/{DATASET_ID}/documents', headers=HEADERS, timeout=10)
print('Status:', r.status_code)
text = r.text
for m in re.finditer(r'"run":"(\w+)"', text):
    print('Run:', m.group(1))
for m in re.finditer(r'"chunk_count":(\d+)', text):
    print('Chunks:', m.group(1))
for m in re.finditer(r'"progress":(\d+)', text):
    print('Progress:', m.group(1))
