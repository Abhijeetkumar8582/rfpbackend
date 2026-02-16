"""Test S3 upload — verifies S3 credentials and connectivity."""
import os
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
os.chdir(backend_root)  # So pydantic finds .env in backend/
sys.path.insert(0, str(backend_root))

from app.config import settings
from app.services.s3 import s3_upload, build_s3_key


def main():
    if not settings.s3_bucket:
        print("FAIL: S3_BUCKET not set in .env")
        sys.exit(1)
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        print("FAIL: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY required in .env")
        sys.exit(1)

    test_content = b"RFP S3 upload test - success"
    test_key = build_s3_key(project_id=1, cluster="test", filename="s3-test.txt")

    try:
        s3_upload(test_content, test_key, "text/plain")
        print(f"OK: Uploaded to s3://{settings.s3_bucket}/{test_key}")
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
