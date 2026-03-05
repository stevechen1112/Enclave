import requests

# Test hr@taiyutech.com 
r = requests.post('http://web:8000/api/v1/auth/login/access-token',
    data={'username': 'hr@taiyutech.com', 'password': 'Test1234!'})
print("Login:", r.status_code)
token = r.json().get('access_token')

import io
files = {'file': ('test2.txt', io.BytesIO(b'HR test file'), 'text/plain')}
r2 = requests.post('http://web:8000/api/v1/documents/upload',
    headers={'Authorization': f'Bearer {token}'},
    files=files)
print("Upload:", r2.status_code, r2.text[:200])
