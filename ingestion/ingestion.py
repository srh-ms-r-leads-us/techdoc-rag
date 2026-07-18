

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import fitz  # PyMuPDF
from chromadb.utils import embedding_functions

from config import cfg

# Logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# Manifest helpers

MANIFEST_FILE = cfg.OUTPUT_DIR / "manifest.json"


def load_manifest() -> dict:
    """Load the manifest from disk. Returns empty dict if it does not exist."""
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_manifest(manifest: dict) -> None:
    """Persist the manifest to disk."""
    cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)


def hash_file(path: Path) -> str:
    """
    Compute the SHA-256 hash of a file.
    Used to detect whether a PDF has changed since it was last ingested.
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8192), b""):
            sha256.update(block)
    return sha256.hexdigest()


# Cleaning + chunking


def clean_text(raw: str) -> str:
    """Remove excessive whitespace, fix hyphenation, clean control chars."""
    text = re.sub(r"-\n(\w)", r"\1", raw)     # fix hyphenated line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)    # collapse excessive newlines
    text = re.sub(r"[ \t]+", " ", text)       # collapse whitespace
    return text.strip()


def extract_chunks_from_pdf(pdf_path: Path) -> list[dict]:
    """
    Extract text from a PDF and split into overlapping chunks.
    Returns a flat list of chunk dicts ready for embedding.
    """
    doc = fitz.open(str(pdf_path))
    chunks = []

    for page_index in range(len(doc)):
        raw_text = doc[page_index].get_text("text")
        text = clean_text(raw_text)

        # Skip near-empty pages
        if len(text) < cfg.MIN_PAGE_CHARS:
            continue

        # Sliding window chunking (word-based)
        words = text.split()
        step = cfg.CHUNK_SIZE - cfg.CHUNK_OVERLAP
        start = 0

        while start < len(words):
            end = start + cfg.CHUNK_SIZE
            chunk_text_value = " ".join(words[start:end])

            # Discard very short chunks (headers, footers)
            if len(chunk_text_value.split()) >= cfg.MIN_CHUNK_WORDS:
                chunk_index = start // step

                chunks.append({
                    # Unique ID — same format used by text_chunker.py
                    "chunk_id": (
                        f"{pdf_path.stem}"
                        f"_p{page_index + 1:03d}"
                        f"_c{chunk_index:02d}"
                    ),
                    "text": chunk_text_value,
                    "metadata": {
                        "doc_name": pdf_path.stem,
                        "source_file": pdf_path.name,
                        "page_num": page_index + 1,
                        "total_pages": len(doc),
                        "chunk_index": chunk_index,
                    },
                })

            if end >= len(words):
                break
            start += step

    doc.close()
    return chunks

# ChromaDB helpers

def get_collection():
    """Open (or create) the ChromaDB collection."""
    cfg.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(cfg.CHROMA_DIR))

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=cfg.EMBED_MODEL
    )

    return client.get_or_create_collection(
        name=cfg.CHROMA_COLLECTION,
        embedding_function=embed_fn,
        metadata={"hnsw:space": cfg.CHROMA_DISTANCE_METRIC},
    )


def delete_chunks_from_chroma(collection, chunk_ids: list[str]) -> None:
    """Delete a specific list of chunk IDs from ChromaDB."""
    if chunk_ids:
        collection.delete(ids=chunk_ids)


def add_chunks_to_chroma(collection, chunks: list[dict]) -> None:
    """Embed and upsert a list of chunk dicts into ChromaDB, in batches."""
    if not chunks:
        return

    batch_size = cfg.EMBED_BATCH_SIZE
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        log.info(f"    embedded batch {i // batch_size + 1} ({len(batch)} chunks)")


# Per-file processing


def process_pdf(pdf_path: Path, collection, manifest: dict) -> None:
    """Ingest a single PDF: extract → clean → chunk → embed → store."""
    chunks = extract_chunks_from_pdf(pdf_path)

    if not chunks:
        log.warning(f"  No usable text extracted from {pdf_path.name} — skipping.")
        return

    add_chunks_to_chroma(collection, chunks)

    manifest[pdf_path.name] = {
        "sha256": hash_file(pdf_path),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "chunk_ids": [c["chunk_id"] for c in chunks],
    }
    log.info(f"  Ingested {pdf_path.name}: {len(chunks)} chunks")



# Main entry point


def run(force: bool = False) -> None:
    manifest = load_manifest()
    collection = get_collection()

    pdf_files = sorted(cfg.PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        log.warning(f"No PDFs found in {cfg.PDF_DIR}")
        return

    seen_files = set()

    for pdf_path in pdf_files:
        seen_files.add(pdf_path.name)
        current_hash = hash_file(pdf_path)
        previous = manifest.get(pdf_path.name)

        if previous and not force:
            if previous["sha256"] == current_hash:
                log.info(f"Unchanged, skipping: {pdf_path.name}")
                continue
            # Content changed — remove old chunks before re-ingesting
            log.info(f"Changed, re-ingesting: {pdf_path.name}")
            delete_chunks_from_chroma(collection, previous.get("chunk_ids", []))
        elif previous and force:
            log.info(f"Force re-ingest: {pdf_path.name}")
            delete_chunks_from_chroma(collection, previous.get("chunk_ids", []))
        else:
            log.info(f"New file: {pdf_path.name}")

        process_pdf(pdf_path, collection, manifest)

    # Handle files removed from the folder since the last run
    for filename in list(manifest.keys()):
        if filename not in seen_files:
            log.info(f"Removed from folder, deleting from Chroma: {filename}")
            delete_chunks_from_chroma(collection, manifest[filename].get("chunk_ids", []))
            del manifest[filename]

    save_manifest(manifest)
    log.info(f"Done. Collection now has {collection.count()} vectors.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest PDFs into ChromaDB.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest all PDFs regardless of manifest state.",
    )
    args = parser.parse_args()
    run(force=args.force)