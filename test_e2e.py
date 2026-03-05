import requests, time, io

r = requests.post('http://web:8000/api/v1/auth/login/access-token',
    data={'username': 'demo@unihr.ai', 'password': 'admin123'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Upload a real txt file
content = "員工手冊測試\n本公司加班費按1.5倍計算，特休依年資給假。".encode()
files = {'file': ('hr-test.txt', io.BytesIO(content), 'text/plain')}
r2 = requests.post('http://web:8000/api/v1/documents/upload', headers=headers, files=files)
doc_id = r2.json().get('id')
print(f"Upload: {r2.status_code}, doc_id={doc_id}")

# Poll status for 60 seconds
for i in range(12):
    time.sleep(5)
    r3 = requests.get(f'http://web:8000/api/v1/documents/{doc_id}', headers=headers)
    status = r3.json().get('status')
    chunks = r3.json().get('chunk_count')
    print(f"  [{(i+1)*5}s] status={status}, chunks={chunks}")
    if status in ('completed', 'failed'):
        break
