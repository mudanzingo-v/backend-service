"""
Storage service tests — document save/delete on local filesystem.

Tests cover the async filesystem operations in ``app/services/storage.py``:
save, delete, and delete-noop for missing files.
"""
from __future__ import annotations

import pytest

from app.services import storage as storage_svc


@pytest.fixture(autouse=True)
def _kyc_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    """Redirect KYC_STORAGE_DIR to a per-test temp directory so tests never
    write to the real ``./mobbit-backend-service_data/kyc/`` tree."""
    monkeypatch.setattr(storage_svc, "KYC_STORAGE_DIR", tmp_path)


# =============================================================================
# save_document
# =============================================================================


async def test_save_document_creates_file() -> None:
    """File is written to the expected subdirectory."""
    content = b"fake-pdf-content-1234"
    path = await storage_svc.save_document(
        provider_id="prov-1",
        doc_type="ine",
        content=content,
        original_name="mi-ine.pdf",
    )
    assert path.endswith(".pdf"), f"expected .pdf extension, got {path}"
    assert "ine_" in path, f"expected doc_type prefix in path, got {path}"

    with open(path, "rb") as f:
        assert f.read() == content


async def test_save_document_uses_original_extension() -> None:
    """File extension is derived from the original filename."""
    path = await storage_svc.save_document(
        provider_id="prov-2",
        doc_type="rfc",
        content=b"xml-data",
        original_name="constancia.xml",
    )
    assert path.endswith(".xml"), f"expected .xml, got {path}"


async def test_save_document_fallback_extension() -> None:
    """Files without an extension get '.bin'."""
    path = await storage_svc.save_document(
        provider_id="prov-3",
        doc_type="bank_statement",
        content=b"data",
        original_name="statement",  # no suffix
    )
    assert path.endswith(".bin"), f"expected .bin, got {path}"


async def test_save_document_uses_provider_subdirectory() -> None:
    """Each provider gets its own subdirectory under KYC_STORAGE_DIR."""
    path = await storage_svc.save_document(
        provider_id="prov-unique-42",
        doc_type="license",
        content=b"abc",
        original_name="license.pdf",
    )
    assert "prov-unique-42" in path, (
        f"expected provider id in path, got {path}"
    )


# =============================================================================
# delete_document
# =============================================================================


async def test_delete_document_removes_file() -> None:
    """Existing file is removed after delete_document."""
    import os

    path = await storage_svc.save_document(
        provider_id="prov-del",
        doc_type="ine",
        content=b"to-be-deleted",
        original_name="doc.pdf",
    )
    assert os.path.exists(path), "file should exist before delete"

    await storage_svc.delete_document(path)
    assert not os.path.exists(path), "file should be gone after delete"


async def test_delete_document_nonexistent_is_noop() -> None:
    """delete_document on a missing path does not raise."""
    # This should not raise any exception
    await storage_svc.delete_document("/tmp/nonexistent-kyc-doc-xyz.bin")
