"""Re-upload a single document: delete old version, upload new one."""
import sys, requests, json, time, os

BASE_URL = "http://localhost:8001"
USERNAME = "admin@example.com"
PASSWORD = "admin123"


def login():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login/access-token",
                      data={"username": USERNAME, "password": PASSWORD})
    return r.json()["access_token"]


def find_doc(token, filename):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_URL}/api/v1/documents/",
                     headers=headers, params={"limit": 200})
    docs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    for d in docs:
        if d.get("filename") == filename or d.get("title") == filename:
            return d
    return None


def delete_doc(token, doc_id):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.delete(f"{BASE_URL}/api/v1/documents/{doc_id}", headers=headers)
    return r.status_code


def upload_doc(token, filepath):
    headers = {"Authorization": f"Bearer {token}"}
    with open(filepath, "rb") as f:
        fname = os.path.basename(filepath)
        r = requests.post(f"{BASE_URL}/api/v1/documents/upload",
                          headers=headers,
                          files={"file": (fname, f, "text/markdown")})
    return r.json()


def wait_complete(token, doc_id, timeout=120):
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(timeout // 3):
        r = requests.get(f"{BASE_URL}/api/v1/documents/{doc_id}", headers=headers)
        status = r.json().get("processing_status", "")
        if status == "completed":
            return True
        if status in ("failed", "error"):
            return False
        time.sleep(3)
    return False


if __name__ == "__main__":
    filepath = r"test-data\company-documents\performance-reviews\2025年度考核-E003-王俊傑.md"
    if len(sys.argv) > 1:
        filepath = sys.argv[1]

    filename = os.path.basename(filepath)
    print(f"Target: {filename}")

    token = login()
    print("Logged in")

    # Find and delete old version
    doc = find_doc(token, filename)
    if doc:
        print(f"Found old doc ID={doc['id']}. Deleting...")
        status = delete_doc(token, doc["id"])
        print(f"Delete status: {status}")
        time.sleep(2)
    else:
        print("No existing doc found, will just upload.")

    # Upload new version
    print("Uploading...")
    result = upload_doc(token, filepath)
    print("Upload response:", json.dumps(result, ensure_ascii=False, indent=2)[:300])
    doc_id = result.get("id")
    if doc_id:
        print("Waiting for embedding...")
        ok = wait_complete(token, doc_id)
        print("Completed!" if ok else "FAILED or timed out")
    else:
        print("No doc_id returned")
