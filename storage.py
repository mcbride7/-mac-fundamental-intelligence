"""Immutable storage for original uploads (Section 66.7 / 66.16).
Files are content-addressed by SHA-256, so the same upload is stored once and
can never be silently replaced. Local disk by default; S3-compatible storage
when S3_BUCKET is set."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.config import settings

ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic", "image/heif", "image/gif",
    "application/pdf", "text/plain", "text/csv",
}

# magic-number checks so a renamed executable cannot pass as an image/PDF
_MAGIC = {
    "application/pdf": [b"%PDF"],
    "image/png": [b"\x89PNG"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/jpg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF8"],
    "image/webp": [b"RIFF"],
}
_BLOCKED_PREFIXES = [b"MZ", b"\x7fELF", b"#!", b"PK\x03\x04"]


class UploadRejected(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_upload(data: bytes, mime: str) -> None:
    if len(data) == 0:
        raise UploadRejected("Empty file")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File larger than {settings.max_upload_mb} MB")
    if mime not in ALLOWED_MIME:
        raise UploadRejected(f"File type {mime} not allowed")
    if any(data.startswith(p) for p in _BLOCKED_PREFIXES):
        raise UploadRejected("Executable or archive content is not allowed")
    magics = _MAGIC.get(mime)
    if magics and not any(data.startswith(m) for m in magics):
        raise UploadRejected(f"File content does not match declared type {mime}")
    # Hook for a real malware scanner (e.g. ClamAV via clamd) in production.
    scanner = os.getenv("CLAMD_HOST")
    if scanner:  # pragma: no cover - requires a running clamd
        import socket

        host, _, port = scanner.partition(":")
        with socket.create_connection((host, int(port or 3310)), timeout=20) as s:
            s.sendall(b"zINSTREAM\0" + len(data).to_bytes(4, "big") + data + (0).to_bytes(4, "big"))
            reply = s.recv(4096)
        if b"FOUND" in reply:
            raise UploadRejected("Malware detected in upload")


def store(data: bytes, filename: str) -> tuple[str, str]:
    """Store bytes immutably. Returns (sha256, storage path/URI)."""
    digest = sha256(data)
    ext = Path(filename).suffix.lower()[:8]
    key = f"uploads/{digest[:2]}/{digest}{ext}"
    if settings.s3_bucket:  # pragma: no cover - requires S3
        import boto3

        s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint_url)
        s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data)
        return digest, f"s3://{settings.s3_bucket}/{key}"
    path = Path(settings.storage_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
        os.chmod(path, 0o444)  # read-only: originals are immutable
    return digest, str(path)


def load(uri: str) -> bytes:
    if uri.startswith("s3://"):  # pragma: no cover
        import boto3

        bucket, _, key = uri[5:].partition("/")
        return boto3.client("s3", endpoint_url=settings.s3_endpoint_url).get_object(
            Bucket=bucket, Key=key)["Body"].read()
    return Path(uri).read_bytes()
