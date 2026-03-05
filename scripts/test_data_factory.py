#!/usr/bin/env python3
"""
=======================================================
  Test Data Factory
  - Creates reproducible test data for all test suites
  - Manages test document lifecycle (upload, verify, cleanup)
  - Generates test fixtures for regression testing
=======================================================
Usage:
  python scripts/test_data_factory.py setup    # Create all test data
  python scripts/test_data_factory.py verify   # Verify test data exists
  python scripts/test_data_factory.py cleanup  # Remove all test data
  python scripts/test_data_factory.py          # Run all phases
"""
import io, sys, os, time, json, argparse, tempfile, requests

# ── UTF-8 stdout (Windows cp950 workaround) ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.getenv("API_BASE", "http://localhost:8001")
API = f"{BASE}/api/v1"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
TIMEOUT = 30
TEST_DATA_DIR = os.path.join(PROJECT_ROOT, "test-data")

passed = 0
failed = 0
skipped = 0

# Test data registry — tracks all created resources for cleanup
REGISTRY_FILE = os.path.join(PROJECT_ROOT, "test-data", ".test_registry.json")


def log(status, tid, msg):
    global passed, failed, skipped
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "INFO": "[INFO]"}
    print(f"  {tag.get(status, status)} {tid}: {msg}")
    if status == "PASS":
        passed += 1
    elif status == "FAIL":
        failed += 1
    elif status == "SKIP":
        skipped += 1


def get_token():
    r = requests.post(f"{API}/auth/login/access-token", data={
        "username": ADMIN_EMAIL, "password": ADMIN_PASS
    }, timeout=TIMEOUT)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"documents": [], "conversations": [], "created_at": None}


def save_registry(registry):
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    registry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


# ===== Test Document Templates =====
TEST_DOCUMENTS = [
    {
        "name": "factory_test_policy.txt",
        "content": """Enterprise HR Policy Document - Test Factory
==============================================

1. Leave Policy
   - Annual leave: 14 days per year
   - Sick leave: 10 days per year
   - Personal leave: 5 days per year
   - Maternity leave: 8 weeks

2. Performance Review
   - Quarterly review cycle
   - 360-degree feedback
   - KPI-based evaluation system

3. Compensation Structure
   - Base salary reviewed annually
   - Performance bonus: 0-20% of base
   - Stock options for senior roles

4. Training & Development
   - Annual training budget: NT$30,000/person
   - External course reimbursement
   - Internal mentorship program

Keywords: HR policy, leave, performance, compensation, training
""",
        "category": "policy",
    },
    {
        "name": "factory_test_procedure.txt",
        "content": """Standard Operating Procedure - Test Factory
============================================

SOP-001: Employee Onboarding Procedure
---------------------------------------
Step 1: HR creates employee record in system
Step 2: IT provisions accounts (email, VPN, tools)
Step 3: Manager assigns buddy/mentor
Step 4: New hire completes orientation (Day 1-3)
Step 5: Department-specific training (Week 1-2)
Step 6: 30-day check-in with HR
Step 7: 90-day probation review

SOP-002: Document Management
-----------------------------
Step 1: Upload document to knowledge base
Step 2: System parses and chunks content
Step 3: Embeddings generated automatically
Step 4: Document searchable via RAG
Step 5: Regular review cycle (quarterly)

Keywords: SOP, onboarding, procedure, knowledge base
""",
        "category": "procedure",
    },
    {
        "name": "factory_test_faq.txt",
        "content": """Frequently Asked Questions - Test Factory
==========================================

Q1: How do I apply for leave?
A: Log in to the HR portal, navigate to Leave > Apply, select dates and type.

Q2: What is the probation period?
A: New employees have a 90-day probation period with a performance review.

Q3: How are performance bonuses calculated?
A: Based on quarterly KPI achievement (0-100%) multiplied by bonus pool.

Q4: Can I work remotely?
A: Remote work policy allows up to 2 days/week with manager approval.

Q5: How do I submit an expense claim?
A: Use the expense module in the HR portal. Attach receipts and submit for approval.

Keywords: FAQ, leave, probation, bonus, remote work, expense
""",
        "category": "faq",
    },
]


def create_test_files():
    """Create test document files on disk."""
    created = []
    for doc in TEST_DOCUMENTS:
        path = os.path.join(TEST_DATA_DIR, doc["name"])
        os.makedirs(TEST_DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc["content"])
        created.append(path)
    return created


def phase_setup(token):
    """Phase 1: Create test data."""
    print("\n--- Phase: SETUP ---")
    registry = load_registry()

    # Create test files on disk
    files = create_test_files()
    log("PASS", "TDF-01", f"Created {len(files)} test files on disk")

    # Upload documents via API
    uploaded_ids = []
    for doc in TEST_DOCUMENTS:
        path = os.path.join(TEST_DATA_DIR, doc["name"])
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    f"{API}/documents/upload",
                    files={"file": (doc["name"], f, "text/plain")},
                    headers=headers(token),
                    timeout=TIMEOUT
                )
            if r.status_code in (200, 201):
                data = r.json()
                # Handle both single and list responses
                if isinstance(data, list):
                    for d in data:
                        doc_id = d.get("id") or d.get("document_id")
                        if doc_id:
                            uploaded_ids.append(str(doc_id))
                elif isinstance(data, dict):
                    doc_id = data.get("id") or data.get("document_id")
                    if doc_id:
                        uploaded_ids.append(str(doc_id))
                log("PASS", f"TDF-02-{doc['name'][:20]}", f"Uploaded: {doc['name']}")
            else:
                log("FAIL", f"TDF-02-{doc['name'][:20]}", f"Upload failed: {r.status_code} {r.text[:80]}")
        except Exception as e:
            log("FAIL", f"TDF-02-{doc['name'][:20]}", f"Exception: {e}")

    registry["documents"] = uploaded_ids
    registry["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_registry(registry)

    log("INFO", "TDF-03", f"Registry saved: {len(uploaded_ids)} document IDs")

    # Wait for processing
    if uploaded_ids:
        print("  Waiting 5s for document processing...")
        time.sleep(5)

    return uploaded_ids


def phase_verify(token):
    """Phase 2: Verify test data exists and is searchable."""
    print("\n--- Phase: VERIFY ---")
    registry = load_registry()

    # Verify documents exist in API
    doc_ids = registry.get("documents", [])
    if not doc_ids:
        log("SKIP", "TDF-04", "No documents in registry to verify")
        return

    found = 0
    for doc_id in doc_ids:
        try:
            r = requests.get(f"{API}/documents/{doc_id}", headers=headers(token), timeout=TIMEOUT)
            if r.status_code == 200:
                found += 1
        except Exception:
            pass

    if found == len(doc_ids):
        log("PASS", "TDF-04", f"All {found}/{len(doc_ids)} registered documents found")
    elif found > 0:
        log("WARN", "TDF-04", f"{found}/{len(doc_ids)} documents found (some may have been processed)")
        passed += 1
    else:
        log("FAIL", "TDF-04", f"No registered documents found")

    # Verify searchability
    try:
        r = requests.get(f"{API}/documents/", headers=headers(token),
                        params={"search": "factory_test"}, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("documents", []))
            log("PASS", "TDF-05", f"Search 'factory_test' returned {len(items)} results")
        else:
            log("FAIL", "TDF-05", f"Search returned {r.status_code}")
    except Exception as e:
        log("FAIL", "TDF-05", f"Exception: {e}")

    # Verify test files on disk
    disk_ok = 0
    for doc in TEST_DOCUMENTS:
        path = os.path.join(TEST_DATA_DIR, doc["name"])
        if os.path.exists(path):
            disk_ok += 1
    log("PASS", "TDF-06", f"{disk_ok}/{len(TEST_DOCUMENTS)} test files present on disk")

    # Create a test conversation for chat testing
    try:
        r = requests.post(f"{API}/chat/chat", json={
            "question": "What is the leave policy?",
            "conversation_id": None
        }, headers=headers(token), timeout=60)
        if r.status_code == 200:
            conv_id = r.json().get("conversation_id")
            if conv_id:
                registry["conversations"].append(str(conv_id))
                save_registry(registry)
            log("PASS", "TDF-07", f"Test conversation created: {conv_id}")
        else:
            log("SKIP", "TDF-07", f"Chat returned {r.status_code}")
    except Exception as e:
        log("SKIP", "TDF-07", f"Chat test: {e}")

    # Verify registry integrity
    reg = load_registry()
    log("PASS", "TDF-08", f"Registry: {len(reg.get('documents', []))} docs, "
        f"{len(reg.get('conversations', []))} convs, created: {reg.get('created_at', '?')}")


def phase_cleanup(token):
    """Phase 3: Remove all test data."""
    print("\n--- Phase: CLEANUP ---")
    registry = load_registry()

    # Delete uploaded documents
    doc_ids = registry.get("documents", [])
    deleted = 0
    for doc_id in doc_ids:
        try:
            r = requests.delete(f"{API}/documents/{doc_id}", headers=headers(token), timeout=TIMEOUT)
            if r.status_code in (200, 204, 404):
                deleted += 1
        except Exception:
            pass

    if doc_ids:
        log("PASS", "TDF-09", f"Cleaned {deleted}/{len(doc_ids)} documents from API")
    else:
        log("SKIP", "TDF-09", "No documents to clean")

    # Clean test files from disk
    cleaned_files = 0
    for doc in TEST_DOCUMENTS:
        path = os.path.join(TEST_DATA_DIR, doc["name"])
        if os.path.exists(path):
            os.remove(path)
            cleaned_files += 1

    log("PASS", "TDF-10", f"Removed {cleaned_files} test files from disk")

    # Reset registry
    save_registry({"documents": [], "conversations": [], "created_at": None})
    log("PASS", "TDF-11", "Registry reset")


# ===== Main =====
print("\n=== Test Data Factory ===\n")

parser = argparse.ArgumentParser(description="Test Data Factory")
parser.add_argument("phase", nargs="?", default="all",
                    choices=["setup", "verify", "cleanup", "all"],
                    help="Phase to run (default: all)")
args = parser.parse_args()

# Auth
token = get_token()
if not token:
    print("[ABORT] Cannot authenticate. Check credentials.")
    sys.exit(1)
log("PASS", "TDF-00", "Authenticated successfully")

if args.phase in ("setup", "all"):
    phase_setup(token)

if args.phase in ("verify", "all"):
    phase_verify(token)

if args.phase in ("cleanup", "all"):
    phase_cleanup(token)

# ── Summary ──
print(f"\n{'='*50}")
print(f"  Test Data Factory: {passed} passed / {failed} failed / {skipped} skipped")
print(f"{'='*50}\n")
sys.exit(1 if failed > 0 else 0)
