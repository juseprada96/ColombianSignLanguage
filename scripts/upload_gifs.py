#!/usr/bin/env python3
"""Upload the GIFs under words/ to a Cloudflare R2 bucket.

R2 is S3-compatible. Create an R2 API token with Object Read & Write access and
set these environment variables before running:

    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET

Optional:

    R2_PUBLIC_BASE_URL   public bucket URL, used only to print an example link

Examples:

    python scripts/upload_gifs.py --skip-existing
    python scripts/upload_gifs.py --prefix csl --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUPPORTED = {".gif"}
CACHE_CONTROL = "public, max-age=604800"
ROOT = Path(__file__).resolve().parent.parent
WORDS = ROOT / "words"


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from .env without overriding real environment vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing {name}. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY and R2_BUCKET (see README)."
        )
    return value


def make_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise SystemExit(
            "boto3 is required. Install it with 'python -m pip install boto3'."
        ) from exc

    account_id = env("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def object_key(path: Path, prefix: str) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return f"{prefix.rstrip('/')}/{rel}" if prefix else rel


def remote_size(client, bucket: str, key: str) -> int | None:
    from botocore.exceptions import ClientError

    try:
        return int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def upload(client, bucket: str, path: Path, key: str, dry_run: bool) -> None:
    if dry_run:
        return
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"ContentType": "image/gif", "CacheControl": CACHE_CONTROL},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", help="Override R2_BUCKET")
    parser.add_argument("--prefix", default="", help="Optional key prefix, e.g. 'csl'")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent uploads (default: 8)")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip objects whose remote size already matches the local GIF",
    )
    parser.add_argument("--dry-run", action="store_true", help="List what would be uploaded")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if not WORDS.is_dir():
        raise SystemExit(f"words/ not found at {WORDS}")

    files = sorted(path for path in WORDS.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED)
    if not files:
        raise SystemExit("No GIFs found under words/")

    if args.dry_run:
        bucket = args.bucket or os.environ.get("R2_BUCKET", "(dry-run)")
        client = None
    else:
        bucket = args.bucket or env("R2_BUCKET")
        client = make_client()

    uploaded = 0
    skipped = 0
    failed: list[tuple[str, str]] = []
    total_bytes = 0

    def task(path: Path):
        key = object_key(path, args.prefix)
        if args.skip_existing and not args.dry_run:
            size = remote_size(client, bucket, key)
            if size == path.stat().st_size:
                return "skipped", key, 0
        upload(client, bucket, path, key, args.dry_run)
        return "uploaded", key, path.stat().st_size

    print(f"Syncing {len(files)} GIF(s) to bucket {bucket!r} ...")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(task, path): path for path in files}
        for done, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            try:
                status, key, size = future.result()
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed.append((str(path.relative_to(ROOT)), str(exc)))
                continue
            if status == "skipped":
                skipped += 1
            else:
                uploaded += 1
                total_bytes += size
            if done % 25 == 0 or done == len(files):
                print(f"  {done}/{len(files)} processed")

    if args.dry_run:
        print(f"Dry run: {len(files)} GIF(s) would be uploaded.")
        return 0

    print(f"Uploaded {uploaded}, skipped {skipped}, failed {len(failed)} ({total_bytes / 1024 / 1024:.1f} MiB).")
    if failed:
        for name, message in failed[:20]:
            print(f"  FAILED {name}: {message}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")
        return 1

    public = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public:
        print(f"Example: {public}/{object_key(files[0], args.prefix)}")
    else:
        print("Set R2_PUBLIC_BASE_URL and put it in config.js to serve the GIFs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
