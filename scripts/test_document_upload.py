"""
Test document upload and chunking APIs.

Usage:
  1. Start the backend: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  2. Run: python scripts/test_document_upload.py

The script:
  - Registers a test user (or reuses existing)
  - Verifies chunking on sample file content
  - Uploads sample_upload_test.txt via POST /api/v1/documents
  - Fetches document metadata via GET /api/v1/documents/{id}
"""
import os
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
os.chdir(backend_root)
sys.path.insert(0, str(backend_root))

import httpx

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"


def main():
    print("=== Document Upload & Chunking Test ===\n")

    # 1) Register test user
    print("1. Registering test user...")
    try:
        r = httpx.post(
            f"{API}/auth/register",
            json={"email": "test-upload@example.com", "name": "Test User", "password": "TestPass123!"},
            timeout=10.0,
        )
        if r.status_code == 200:
            user_id = r.json()["id"]
            print(f"   OK: User created (id={user_id})")
        elif r.status_code == 400:
            r2 = httpx.post(
                f"{API}/auth/login",
                json={"email": "test-upload@example.com", "password": "TestPass123!"},
                timeout=10.0,
            )
            if r2.status_code != 200:
                print(f"   FAIL: Login failed: {r2.text}")
                sys.exit(1)
            user_id = r2.json()["user"]["id"]
            print(f"   OK: User exists (id={user_id})")
        else:
            print(f"   FAIL: Register failed: {r.status_code} {r.text}")
            sys.exit(1)
    except httpx.ConnectError:
        print("   FAIL: Cannot connect. Start backend: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    # 2) Test chunking on sample file content
    sample_path = Path(__file__).parent / "sample_upload_test.txt"
    if not sample_path.exists():
        print(f"   FAIL: Sample file not found: {sample_path}")
        sys.exit(1)

    text = sample_path.read_text(encoding="utf-8")
    from app.services.chunking import chunk_text_by_words

    chunks = chunk_text_by_words(text, words_per_chunk=200, overlap_words=30)
    print(f"\n2. Chunking test: {len(text)} chars -> {len(chunks)} chunks")
    for i, c in enumerate(chunks[:5]):
        preview = (c[:60] + "...") if len(c) > 60 else c
        print(f"   Chunk {i+1}: {len(c)} chars - {preview}")
    if len(chunks) > 5:
        print(f"   ... and {len(chunks) - 5} more")

    # 3) Upload document
    print("\n3. Uploading document via POST /api/v1/documents...")
    try:
        with open(sample_path, "rb") as f:
            file_content = f.read()
        r = httpx.post(
            f"{API}/documents",
            data={"project_id": "1", "uploaded_by": str(user_id)},
            files={"file": ("sample_upload_test.txt", file_content, "text/plain")},
            timeout=60.0,
        )
        if r.status_code == 200:
            doc_id = r.json()["id"]
            print(f"   OK: Document uploaded (id={doc_id})")
        else:
            try:
                err = r.json()
                detail = err.get("detail", err)
            except Exception:
                detail = r.text
            print(f"   FAIL: Upload failed {r.status_code}: {detail}")
            sys.exit(1)
    except Exception as e:
        print(f"   FAIL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # 4) Get document metadata
    print("\n4. Fetching document metadata via GET /api/v1/documents/{id}...")
    r = httpx.get(f"{API}/documents/{doc_id}", timeout=10.0)
    if r.status_code == 200:
        doc = r.json()
        print(f"   OK: filename={doc.get('filename')}, status={doc.get('status')}, cluster={doc.get('cluster')}")
    else:
        print(f"   FAIL: {r.status_code} {r.text[:200]}")

    print("\n=== Test complete ===")


if __name__ == "__main__":
    main()
