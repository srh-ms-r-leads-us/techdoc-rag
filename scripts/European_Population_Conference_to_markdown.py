from pathlib import Path
from bs4 import BeautifulSoup
from bs4 import NavigableString
from bs4 import Tag

from techdoc_rag.config.constants import PROJECT_ROOT

import re


def clean_text(text):
    if not text:
        return None

    text = text.replace("\xa0", " ")

    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def heading_prefix(tag_name):
    """
    Convert heading tags into markdown-style prefixes.
    """

    mapping = {
        "h1": "# ",
        "h2": "## ",
        "h3": "### ",
        "h4": "#### ",
        "h5": "##### ",
        "h6": "###### ",
    }

    return mapping.get(tag_name, "")


def extract_recommendation_txt(html_path):
    """
    Extract content from:

        div#block-unece-content

    Starting from:

        <h5 id="pre">PREFACE</h5>

    Output plain txt with heading markers.
    """

    html_path = Path(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")

    # =====================================================
    # locate main block
    # =====================================================

    block_content = soup.select_one(
        "div#block-unece-content"
    )

    if not block_content:
        raise ValueError(
            "Cannot find div#block-unece-content"
        )

    # =====================================================
    # remove useless tags
    # =====================================================

    for tag in block_content.select(
        "script, style, nav, footer, header"
    ):
        tag.decompose()

    # =====================================================
    # locate PREFACE
    # =====================================================

    start_node = block_content.select_one(
        "h5#pre"
    )

    if not start_node:
        raise ValueError(
            "Cannot find h5#pre"
        )

    # =====================================================
    # extract text
    # =====================================================

    lines = []

    # include PREFACE node itself
    all_nodes = [start_node]

    # include everything after PREFACE
    all_nodes.extend(list(start_node.next_siblings))

    for node in all_nodes:

        # =================================================
        # html tags
        # =================================================

        if isinstance(node, Tag):

            tag_name = node.name.lower()

            text = clean_text(
                node.get_text(" ", strip=True)
            )

            if not text:
                continue

            # headings
            if tag_name in {
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            }:
                prefix = heading_prefix(tag_name)

                lines.append(f"\n{prefix}{text}\n")

            # ordered/unordered lists
            elif tag_name in {"ol", "ul"}:

                for li in node.find_all("li", recursive=False):

                    li_text = clean_text(
                        li.get_text(" ", strip=True)
                    )

                    if li_text:
                        lines.append(f"- {li_text}")

                lines.append("")

            # tables
            elif tag_name == "table":

                rows = []

                for tr in node.find_all("tr"):

                    cells = []

                    for cell in tr.find_all(
                        ["th", "td"]
                    ):
                        cell_text = clean_text(
                            cell.get_text(
                                " ",
                                strip=True,
                            )
                        )

                        if cell_text:
                            cells.append(cell_text)

                    if cells:
                        rows.append(
                            " | ".join(cells)
                        )

                if rows:
                    lines.extend(rows)
                    lines.append("")

            # normal block text
            else:
                lines.append(text)

        # =================================================
        # raw text nodes
        # =================================================

        elif isinstance(node, NavigableString):

            text = clean_text(str(node))

            if text:
                lines.append(text)

    # =====================================================
    # cleanup
    # =====================================================

    content = "\n\n".join(lines)

    content = re.sub(
        r"\n{3,}",
        "\n\n",
        content,
    )

    content = clean_text(content)

    # =====================================================
    # output path
    # =====================================================

    doc_name = html_path.stem

    output_dir = (
        PROJECT_ROOT
        / "data"
        / "raw"
        / "docs"
        / doc_name
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{doc_name}.txt"
    )

    # =====================================================
    # write txt
    # =====================================================

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


# =========================================================
# example
# =========================================================

if __name__ == "__main__":

    html_file = (
        PROJECT_ROOT
        / "data"
        / "raw"
        / "raw_detail_page"
        / "European Population Conference.html"
    )

    txt_path = extract_recommendation_txt(
        html_file
    )

    print(txt_path)