import re
import uuid
import unicodedata
from collections import Counter
from pathlib import Path
import pdfplumber
from tinydb import TinyDB
 
PDF_FOLDER = "/Users/ritu/Documents/Semester 2/Case Study 1/techdoc-rag/data/tree"
DB_FILE    = "tree_db.json"
 
HEADING_RE = re.compile(r"^([A-Z]?\d+(?:\.\d+){0,2})\s{1,4}([A-Z].{3,80})$")
DEPTH_TO_LEVEL = {1: "chapter", 2: "section", 3: "subsection"}
 
 
def clean(text: str) -> str:
    """Preprocess: unicode normalise, fix hyphen line-breaks, remove URLs/noise, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"') \
               .replace("\u2013", "-").replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"-\n\s*", "", text)                   # fix hyphenated line breaks
    text = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", "", text)  # remove URLs/emails
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f]", "", text)       # remove control chars
    text = re.sub(r"[ \t]+", " ", text)                  # collapse spaces
    return text.strip()
 
 
def build_tree(pdf_path: Path) -> list[dict]:
    all_lines = []
    pages_lines = []
 
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            lines = (page.extract_text() or "").splitlines()
            pages_lines.append((page_num, lines))
            all_lines.extend(lines)
 
    # Remove repeated header/footer lines
    boilerplate = {l.strip() for l, c in Counter(l.strip() for l in all_lines).items() if c >= 3}
 
    nodes, stack = [], {}
 
    for page_num, lines in pages_lines:
        for raw in lines:
            line = clean(raw)
            if not line or line.strip() in boilerplate or len(line) < 4:
                continue
 
            m = HEADING_RE.match(line)
            if m:
                number, title, depth = m.group(1), m.group(2).strip(), m.group(1).count(".") + 1
                parent = next((stack[d] for d in range(depth - 1, 0, -1) if d in stack), None)
                node = {
                    "id":        uuid.uuid4().hex[:8],
                    "level":     DEPTH_TO_LEVEL.get(depth, "subsection"),
                    "number":    number,
                    "title":     title,
                    "text":      "",
                    "page":      page_num,
                    "source":    pdf_path.name,
                    "parent_id": parent["id"] if parent else None,
                    "path":      (parent["path"] + " > " if parent else "") + f"{number} {title}",
                }
                stack = {d: n for d, n in stack.items() if d < depth}
                stack[depth] = node
                nodes.append(node)
            elif stack:
                deepest = stack[max(stack)]
                deepest["text"] = (deepest["text"] + " " + line).strip()
 
    return nodes
 
 
def main():
    folder = Path(PDF_FOLDER)
    db = TinyDB(DB_FILE)
    table = db.table("tree")
 
    for pdf_path in folder.glob("*.pdf"):
        print(f"Ingesting: {pdf_path.name}")
        try:
            nodes = build_tree(pdf_path)
        except Exception as e:
            print(f"  ✗ Skipped: {e}")
            continue
 
        from tinydb import Query
        table.remove(Query().source == pdf_path.name)
        table.insert_multiple(nodes)
        print(f"  → {len(nodes)} nodes saved to {DB_FILE}")
 
        # Print tree
        for node in nodes:
            indent = "  " * node["path"].count(">")
            icon = {"chapter": "📂", "section": "📁", "subsection": "📎"}.get(node["level"], "•")
            print(f"{indent}{icon} [{node['level']}] {node['number']} {node['title']}  (p.{node['page']})")
 
    db.close()
 
if __name__ == "__main__":
    main()