#!/usr/bin/env python3
"""Sync CloudFront access logs from S3 to the local logs/ directory.

Usage:
    CF_LOGS_BUCKET=my-hostname-cf-logs uv run python scripts/sync_logs.py

The bucket name is printed as the 'LogsBucketName' output of `cdk deploy`.
Requires AWS CLI configured with read access to the logs bucket.
"""
import os
import subprocess
import sys
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"


def main() -> None:
    bucket = os.environ.get("CF_LOGS_BUCKET")
    if not bucket:
        sys.exit("Set CF_LOGS_BUCKET to the CloudFront logs bucket name.")

    LOGS_DIR.mkdir(exist_ok=True)

    subprocess.run(
        ["aws", "s3", "sync", f"s3://{bucket}/cf-logs/", str(LOGS_DIR)],
        check=True,
    )
    print(f"Logs synced to {LOGS_DIR}/")


if __name__ == "__main__":
    main()
