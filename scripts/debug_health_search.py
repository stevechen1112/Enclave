import requests, json, time

token = requests.post('http://localhost:8001/api/v1/auth/login/access-token',
    data={'username':'admin@example.com','password':'admin123'}).json()['access_token']
headers = {'Authorization': 'Bearer ' + token}

t0 = time.time()
r = requests.post('http://localhost:8001/api/v1/kb/search', headers=headers,
    json={'query': '王俊傑健康檢查異常項目', 'top_k': 8})
elapsed = time.time() - t0
print(f'Search time: {elapsed:.2f}s')
data = r.json()
for item in data.get('results', []):
    sc = item.get('score', 0)
    fn = item.get('filename', '?')
    ci = item.get('chunk_index', '?')
    ct = item.get('content', '')[:80]
    print(f'score={sc:.4f} | {fn} [chunk {ci}]')
    print(f'  {ct}')
    print()

# Also test performance query
print('---')
r2 = requests.post('http://localhost:8001/api/v1/kb/search', headers=headers,
    json={'query': '王俊傑2025績效考核總分等級', 'top_k': 8})
for item in r2.json().get('results', []):
    sc = item.get('score', 0)
    fn = item.get('filename', '?')
    ci = item.get('chunk_index', '?')
    ct = item.get('content', '')[:80]
    print(f'score={sc:.4f} | {fn} [chunk {ci}]')
    print(f'  {ct}')
    print()
