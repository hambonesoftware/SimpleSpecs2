"""Tests ensuring the headers endpoint reuses cached parse artifacts."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.config import get_settings, reset_settings_cache
from backend.database import get_engine, reset_database_state
from backend.models import Document
from backend.services.headers import HeaderExtractionResult, HeaderNode
from backend.services.pdf_native import ParsedBlock, ParsedPage, ParseResult


def _reload_app_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "app.db"
    upload_dir = tmp_path / "uploads"
    export_dir = tmp_path / "exports"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("EXPORT_DIR", str(export_dir))
    monkeypatch.setenv("HEADERS_MODE", "llm_full")

    reset_settings_cache()
    reset_database_state()

    import backend.paths as paths

    importlib.reload(paths)
    import backend.main as main

    importlib.reload(main)


def _create_document(session: Session) -> Document:
    document = Document(filename="doc.pdf", checksum="headers-cache-checksum")
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _stub_parse_factory(counter: list[int]):
    def _stub_parse(document_path, *, settings):  # noqa: ANN001 - FastAPI dependency signature
        counter[0] += 1
        block = ParsedBlock(
            text="Heading",
            bbox=(0.0, 0.0, 10.0, 5.0),
            font="Arial",
            font_size=12.0,
            source="pymupdf",
        )
        page = ParsedPage(
            page_number=0,
            width=612.0,
            height=792.0,
            blocks=[block],
        )
        return ParseResult(pages=[page], has_ocr=True, used_mineru=False)

    return _stub_parse


@pytest.mark.usefixtures("tmp_path")
def test_headers_endpoint_reuses_cached_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reload_app_environment(tmp_path, monkeypatch)

    from backend.main import app

    parse_calls = [0]
    stub_parse = _stub_parse_factory(parse_calls)
    monkeypatch.setattr("backend.api.headers.parse_pdf", stub_parse)
    monkeypatch.setattr("backend.routers.headers.parse_pdf", stub_parse)

    async def _stub_extract_headers_and_chunks(
        document_bytes: bytes, **_: Any
    ) -> tuple[dict, None]:
        return (
            {
                "headers": [
                    {
                        "text": "Heading",
                        "number": "1",
                        "level": 1,
                        "global_idx": 0,
                        "page": 1,
                    }
                ],
                "sections": [],
                "mode": "stub",
                "lines": [
                    {
                        "text": "Heading",
                        "global_idx": 0,
                        "page": 1,
                        "line_idx": 0,
                    }
                ],
                "doc_hash": "stub-hash",
                "excluded_pages": [],
                "messages": [],
                "fenced_text": "#headers#\n#/headers#",
            },
            None,
        )

    monkeypatch.setattr(
        "backend.api.headers.extract_headers_and_chunks",
        _stub_extract_headers_and_chunks,
    )
    monkeypatch.setattr(
        "backend.routers.headers.extract_headers_and_chunks",
        _stub_extract_headers_and_chunks,
    )

    def _stub_extract_headers(*_: Any, **__: Any) -> HeaderExtractionResult:
        node = HeaderNode(title="Heading", numbering="1", page=1)
        return HeaderExtractionResult(
            outline=[node],
            fenced_text="#headers#\n#/headers#",
            source="stub",
            messages=[],
        )

    monkeypatch.setattr("backend.api.headers.extract_headers", _stub_extract_headers)

    monkeypatch.setattr(
        "backend.api.headers.build_and_store_sections",
        lambda **_: [],
    )

    settings = get_settings()

    try:
        with TestClient(app) as client:
            engine = get_engine()
            with Session(engine) as session:
                document = _create_document(session)
                document_id = document.id

            assert document_id is not None

            document_dir = settings.upload_dir / str(document_id)
            document_dir.mkdir(parents=True, exist_ok=True)
            (document_dir / "doc.pdf").write_bytes(b"PDF")

            first = client.post(f"/api/headers/{document_id}")
            assert first.status_code == 200, first.text
            assert parse_calls[0] == 1

            second = client.post(f"/api/headers/{document_id}")
            assert second.status_code == 200, second.text
            assert parse_calls[0] == 1
    finally:
        reset_settings_cache()
        reset_database_state()
