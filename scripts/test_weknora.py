"""Test WeKnora API integration with correct endpoints."""
import httpx

# Login
r = httpx.post('http://localhost:8081/api/v1/auth/login', json={
    'email': 'enclave@enclave.local', 'password': 'Enclave2024!'
}, timeout=10)
token = r.json()['token']
headers = {'Authorization': f'Bearer {token}'}

# List KBs
r2 = httpx.get('http://localhost:8081/api/v1/knowledge-bases', headers=headers, timeout=10)
data = r2.json()
print(f"KBs: {r2.status_code}")
kb_id = None
for kb in data.get('data', []):
    print(f"  KB: {kb['name']} id={kb['id']}")
    kb_id = kb['id']

if kb_id:
    # Upload document (correct path: /knowledge/file)
    pdf_path = 'C:/Users/User/Desktop/Enclave/test-data/sample_manual.pdf'
    with open(pdf_path, 'rb') as f:
        r3 = httpx.post(
            f'http://localhost:8081/api/v1/knowledge-bases/{kb_id}/knowledge/file',
            headers=headers,
            files={'file': ('sample_manual.pdf', f, 'application/pdf')},
            timeout=30
        )
    print(f"Upload: {r3.status_code} {r3.text[:300]}")

    # Search
    r4 = httpx.get('http://localhost:8081/api/v1/knowledge/search',
                   headers=headers,
                   params={'query': 'test', 'top_k': 5},
                   timeout=10)
    print(f"Search: {r4.status_code} {r4.text[:300]}")

    # Wiki rebuild
    r5 = httpx.post(f'http://localhost:8081/api/v1/knowledgebase/{kb_id}/wiki/rebuild-links',
                    headers=headers, timeout=10)
    print(f"Wiki rebuild: {r5.status_code} {r5.text[:200]}")
