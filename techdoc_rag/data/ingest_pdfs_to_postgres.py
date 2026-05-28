from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Literal

import psycopg
from dotenv import load_dotenv
from loguru import logger
from techdoc_rag.config.constants import PROJECT_ROOT


DocumentType = Literal["pdf", "markdown"]

DOCS_ROOT = PROJECT_ROOT / "data" / "raw" / "documentation"
PDF_SEQUENCE_PATTERN = re.compile(r"^(\d{3})_.+\.pdf$", re.IGNORECASE)

CREATE_TABLES_SQL = """
DROP TABLE IF EXISTS document_files;
DROP TABLE IF EXISTS document_records;

CREATE TABLE document_records (
    id BIGSERIAL PRIMARY KEY,

    record_name TEXT NOT NULL,
    relative_record_path TEXT NOT NULL,

    record_type TEXT NOT NULL CHECK (record_type IN ('pdf', 'markdown')),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_document_records_relative_record_path
        UNIQUE (relative_record_path)
);

CREATE TABLE document_files (
    id BIGSERIAL PRIMARY KEY,

    record_id BIGINT NOT NULL,

    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'markdown')),
    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'text/markdown')),

    filename TEXT NOT NULL,
    file_ext TEXT NOT NULL CHECK (file_ext IN ('.pdf', '.md')),
    relative_file_path TEXT NOT NULL,

    sequence_no INTEGER,

    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    sha256 TEXT NOT NULL,

    content BYTEA NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_document_files_record_id
        FOREIGN KEY (record_id)
        REFERENCES document_records(id)
        ON DELETE RESTRICT,

    CONSTRAINT uq_document_files_relative_file_path
        UNIQUE (relative_file_path),

    CONSTRAINT ck_document_files_pdf_sequence_no
        CHECK (
            (file_type = 'pdf' AND sequence_no IS NOT NULL)
            OR
            (file_type = 'markdown' AND sequence_no IS NULL)
        )
);

CREATE INDEX idx_document_files_record_id
ON document_files(record_id);

CREATE INDEX idx_document_files_file_type
ON document_files(file_type);

CREATE INDEX idx_document_files_sha256
ON document_files(sha256);

CREATE INDEX idx_document_files_record_sequence
ON document_files(record_id, sequence_no);
"""


def get_connection() -> psycopg.Connection:
    """Create a PostgreSQL connection from environment variables."""
    load_dotenv(PROJECT_ROOT / ".env")

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "techdoc_rag")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")

    conninfo = (
        f"host={host} "
        f"port={port} "
        f"dbname={db} "
        f"user={user} "
        f"password={password}"
    )

    return psycopg.connect(conninfo)


def ensure_tables(conn: psycopg.Connection) -> None:
    """Drop and recreate the document storage tables."""
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLES_SQL)

    conn.commit()


def sha256_file(path: Path) -> str:
    """Calculate the SHA-256 hash of a file."""
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def read_binary(path: Path) -> bytes:
    """Read a file as raw binary content."""
    with path.open("rb") as f:
        return f.read()


def get_content_type(file_type: DocumentType) -> str:
    """Return the MIME-like content type stored in the database."""
    if file_type == "pdf":
        return "application/pdf"

    if file_type == "markdown":
        return "text/markdown"

    raise ValueError(f"Unsupported file_type: {file_type}")


def detect_record_type(record_dir: Path) -> DocumentType | None:
    """
    Detect whether a record folder contains PDF files or Markdown files.

    A record folder must not contain both PDF and Markdown files.
    """
    pdf_files = sorted(
        p for p in record_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    md_files = sorted(
        p for p in record_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
    )

    if pdf_files and md_files:
        raise ValueError(
            f"Mixed PDF and Markdown files are not allowed in one record folder: {record_dir}"
        )

    if pdf_files:
        return "pdf"

    if md_files:
        return "markdown"

    return None


def parse_pdf_sequence_no(pdf_path: Path) -> int:
    """
    Parse the sequence number from a PDF filename.

    Expected format:
        000_somename.pdf
        001_chapter-title.pdf
    """
    match = PDF_SEQUENCE_PATTERN.match(pdf_path.name)

    if match is None:
        raise ValueError(
            "PDF filename must match the format '000_somename.pdf': "
            f"{pdf_path.name}"
        )

    return int(match.group(1))


def parse_sequence_no(path: Path, file_type: DocumentType) -> int | None:
    """Return the PDF sequence number, or None for Markdown files."""
    if file_type == "pdf":
        return parse_pdf_sequence_no(path)

    return None


def get_files_for_record(record_dir: Path, record_type: DocumentType) -> list[Path]:
    """Return files in a record folder in deterministic order."""
    if record_type == "pdf":
        return sorted(
            (
                p for p in record_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".pdf"
            ),
            key=parse_pdf_sequence_no,
        )

    return sorted(
        p for p in record_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
    )


def upsert_record(
    conn: psycopg.Connection,
    record_dir: Path,
    record_type: DocumentType,
) -> int:
    """Insert or update one document record and return its database id."""
    relative_record_path = record_dir.relative_to(DOCS_ROOT).as_posix()
    record_name = record_dir.name

    sql = """
    INSERT INTO document_records (
        record_name,
        relative_record_path,
        record_type,
        updated_at
    )
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT (relative_record_path)
    DO UPDATE SET
        record_name = EXCLUDED.record_name,
        record_type = EXCLUDED.record_type,
        updated_at = NOW()
    RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record_name,
                relative_record_path,
                record_type,
            ),
        )
        row = cur.fetchone()

    if row is None:
        raise RuntimeError(f"Failed to upsert document record: {record_dir}")

    return int(row[0])


def insert_document_file(
    conn: psycopg.Connection,
    record_id: int,
    file_path: Path,
    file_type: DocumentType,
) -> int | None:
    """Insert one document file as binary content."""
    relative_file_path = file_path.relative_to(DOCS_ROOT).as_posix()
    filename = file_path.name
    file_ext = file_path.suffix.lower()
    content_type = get_content_type(file_type)
    sequence_no = parse_sequence_no(file_path, file_type)
    file_size_bytes = file_path.stat().st_size
    file_hash = sha256_file(file_path)
    content = read_binary(file_path)

    sql = """
    INSERT INTO document_files (
        record_id,
        file_type,
        content_type,
        filename,
        file_ext,
        relative_file_path,
        sequence_no,
        file_size_bytes,
        sha256,
        content,
        updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (relative_file_path)
    DO NOTHING
    RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record_id,
                file_type,
                content_type,
                filename,
                file_ext,
                relative_file_path,
                sequence_no,
                file_size_bytes,
                file_hash,
                psycopg.Binary(content),
            ),
        )
        row = cur.fetchone()

    if row is None:
        logger.info(f"Skipped existing file: {relative_file_path}")
        return None

    file_id = int(row[0])

    logger.info(
        f"Inserted file: id={file_id}, "
        f"type={file_type}, "
        f"content_type={content_type}, "
        f"sequence_no={sequence_no}, "
        f"size={file_size_bytes}, "
        f"path={relative_file_path}"
    )

    return file_id


def ingest_all_records(conn: psycopg.Connection) -> None:
    """Ingest all document record folders under DOCS_ROOT."""
    if not DOCS_ROOT.exists():
        raise FileNotFoundError(f"DOCS_ROOT does not exist: {DOCS_ROOT}")

    record_dirs = sorted(p for p in DOCS_ROOT.iterdir() if p.is_dir())

    logger.info(f"DOCS_ROOT={DOCS_ROOT}")
    logger.info(f"Found record folders: {len(record_dirs)}")

    inserted_count = 0
    skipped_count = 0
    empty_count = 0
    failed_count = 0

    for record_dir in record_dirs:
        try:
            record_type = detect_record_type(record_dir)

            if record_type is None:
                logger.warning(f"No PDF or Markdown files found in: {record_dir}")
                empty_count += 1
                continue

            files = get_files_for_record(record_dir, record_type)

            record_id = upsert_record(conn, record_dir, record_type)

            logger.info(
                f"Record id={record_id}, "
                f"type={record_type}, "
                f"name={record_dir.name}, "
                f"file_count={len(files)}"
            )

            for file_path in files:
                file_id = insert_document_file(
                    conn=conn,
                    record_id=record_id,
                    file_path=file_path,
                    file_type=record_type,
                )

                if file_id is None:
                    skipped_count += 1
                else:
                    inserted_count += 1

            conn.commit()

        except Exception as exc:
            conn.rollback()
            failed_count += 1
            logger.exception(f"Failed to ingest record folder: {record_dir}. Error: {exc}")

    logger.info(f"Inserted files: {inserted_count}")
    logger.info(f"Skipped files: {skipped_count}")
    logger.info(f"Empty record folders: {empty_count}")
    logger.info(f"Failed record folders: {failed_count}")


def main() -> None:
    """Run the ingestion pipeline."""
    with get_connection() as conn:
        ensure_tables(conn)
        ingest_all_records(conn)


if __name__ == "__main__":
    main()
