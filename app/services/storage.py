"""
File storage abstraction for KYC documents.

Currently uses local filesystem; can be swapped for S3 by replacing
the `save_document` implementation.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings

# Base directory for uploaded documents (configurable, defaults to ./data/kyc)
KYC_STORAGE_DIR = Path(settings.app_name + "_data") / "kyc"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


async def save_document(
    provider_id: str,
    doc_type: str,
    content: bytes,
    original_name: str,
) -> str:
    """Save a document to local filesystem. Returns the relative file path."""
    provider_dir = KYC_STORAGE_DIR / provider_id
    _ensure_dir(provider_dir)

    ext = Path(original_name).suffix or ".bin"
    filename = f"{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = provider_dir / filename

    # Write asynchronously via run_in_executor to avoid blocking
    import asyncio
    loop = asyncio.get_running_loop()

    def _write() -> None:
        file_path.write_bytes(content)

    await loop.run_in_executor(None, _write)
    return str(file_path)


async def delete_document(file_path: str) -> None:
    """Delete a document from local filesystem. No-op if missing."""
    path = Path(file_path)
    if path.exists():
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, path.unlink)
