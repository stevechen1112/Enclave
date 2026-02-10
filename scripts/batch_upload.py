"""
批量上傳測試文件到 UniHR SaaS API
"""
import os, sys, time, requests, glob

BASE_URL = "http://localhost:8000"
HR_USER = "hr@taiyutech.com"
HR_PASS = "Test1234!"
DOC_DIR = os.path.join(os.path.dirname(__file__), "..", "test-data", "company-documents")

# 支援的副檔名
SUPPORTED_EXT = {".pdf", ".txt", ".md", ".csv", ".jpg", ".jpeg", ".png", ".docx", ".xlsx", ".html", ".json", ".rtf"}

def login():
    resp = requests.post(f"{BASE_URL}/api/v1/auth/login/access-token",
                         data={"username": HR_USER, "password": HR_PASS})
    resp.raise_for_status()
    return resp.json()["access_token"]

def upload_file(token, filepath):
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    
    mime_map = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".json": "application/json",
        ".rtf": "application/rtf",
    }
    
    content_type = mime_map.get(ext, "application/octet-stream")
    
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, content_type)}
        resp = requests.post(
            f"{BASE_URL}/api/v1/documents/upload",
            files=files,
            headers={"Authorization": f"Bearer {token}"}
        )
    
    return resp.status_code, resp.json() if resp.status_code == 200 else resp.text

def main():
    print("=" * 60)
    print("批量上傳測試文件")
    print("=" * 60)
    
    # Login
    print("\n🔐 登入中...")
    token = login()
    print(f"   ✅ Token: {token[:20]}...")
    
    # Collect files
    all_files = []
    for root, dirs, files in os.walk(DOC_DIR):
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXT:
                all_files.append(os.path.join(root, f))
    
    print(f"\n📁 找到 {len(all_files)} 個支援的文件")
    
    # Upload
    success = 0
    failed = 0
    results = []
    
    for i, filepath in enumerate(all_files, 1):
        filename = os.path.basename(filepath)
        size_kb = os.path.getsize(filepath) / 1024
        print(f"\n   [{i}/{len(all_files)}] 上傳 {filename} ({size_kb:.1f} KB)...", end=" ")
        
        try:
            status, data = upload_file(token, filepath)
            if status == 200:
                doc_id = data.get("id", "?")
                print(f"✅ id={doc_id[:8]}...")
                results.append({"file": filename, "id": doc_id, "status": "ok"})
                success += 1
            else:
                print(f"❌ HTTP {status}: {str(data)[:100]}")
                results.append({"file": filename, "status": "fail", "error": str(data)[:100]})
                failed += 1
        except Exception as e:
            print(f"❌ {e}")
            results.append({"file": filename, "status": "error", "error": str(e)})
            failed += 1
    
    print(f"\n{'=' * 60}")
    print(f"上傳完成: ✅ {success} 成功, ❌ {failed} 失敗")
    print(f"{'=' * 60}")
    
    # Wait for processing
    if success > 0:
        print(f"\n⏳ 等待 Worker 處理 {success} 個文件...")
        doc_ids = [r["id"] for r in results if r["status"] == "ok"]
        
        max_wait = 300  # 5 minutes
        check_interval = 10
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(check_interval)
            elapsed += check_interval
            
            # Check status
            completed = 0
            processing = 0
            fail = 0
            
            for doc_id in doc_ids:
                try:
                    resp = requests.get(
                        f"{BASE_URL}/api/v1/documents/{doc_id}",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    if resp.status_code == 200:
                        doc = resp.json()
                        st = doc.get("status", "unknown")
                        if st == "completed":
                            completed += 1
                        elif st in ("failed",):
                            fail += 1
                        else:
                            processing += 1
                except:
                    processing += 1
            
            print(f"   [{elapsed}s] 完成={completed}, 處理中={processing}, 失敗={fail}")
            
            if processing == 0:
                break
        
        print(f"\n✅ 處理完成: {completed} completed, {fail} failed")

if __name__ == "__main__":
    main()
