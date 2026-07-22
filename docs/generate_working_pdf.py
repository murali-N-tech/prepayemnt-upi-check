from __future__ import annotations

from datetime import date
from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "EDGE_UPI_WORKING_GUIDE.md"
OUTPUT = ROOT / "Edge_UPI_Working_Guide.pdf"

PAGE_WIDTH = 8.27
PAGE_HEIGHT = 11.69
LEFT = 0.08
RIGHT = 0.92
TOP = 0.95
BOTTOM = 0.06

BODY_SIZE = 10.5
H1_SIZE = 20
H2_SIZE = 14
LINE_STEP = 0.026


def wrap_line(text: str, width: int = 92) -> list[str]:
    if not text.strip():
        return [""]
    return textwrap.wrap(
        text,
        width=width,
        replace_whitespace=False,
        drop_whitespace=False,
    ) or [text]


def parse_markdown_lines(raw_text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    in_code = False

    for raw in raw_text.splitlines():
        stripped = raw.rstrip()

        if stripped.startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            for piece in wrap_line(stripped, width=82):
                lines.append(("code", piece))
            lines.append(("body", ""))
            continue

        if stripped.startswith("# "):
            lines.append(("h1", stripped[2:].strip()))
            continue

        if stripped.startswith("## "):
            lines.append(("h2", stripped[3:].strip()))
            continue

        if stripped.startswith("### "):
            lines.append(("h2", stripped[4:].strip()))
            continue

        if stripped.startswith("- "):
            bullet = f"• {stripped[2:].strip()}"
            for i, piece in enumerate(wrap_line(bullet, width=88)):
                lines.append(("body", piece if i == 0 else f"  {piece}"))
            continue

        if stripped.startswith("1. "):
            for piece in wrap_line(stripped, width=88):
                lines.append(("body", piece))
            continue

        if stripped:
            for piece in wrap_line(stripped, width=92):
                lines.append(("body", piece))
        else:
            lines.append(("body", ""))

    return lines


def draw_header_footer(fig, page_no: int) -> None:
    fig.text(
        LEFT,
        0.985,
        "Edge AI UPI Behavioural Risk Intelligence System",
        fontsize=9,
        color="#444444",
        va="top",
    )
    fig.text(
        RIGHT,
        0.02,
        f"Page {page_no}",
        fontsize=9,
        color="#444444",
        ha="right",
        va="bottom",
    )


def render_pdf(lines: list[tuple[str, str]]) -> None:
    page_no = 0
    fig = None
    y = TOP
    pdf = PdfPages(OUTPUT)

    try:
        for kind, text in lines:
            needed = LINE_STEP * (1.8 if kind == "h1" else 1.5 if kind == "h2" else 1.0)

            if fig is None or y - needed < BOTTOM:
                if fig is not None:
                    draw_header_footer(fig, page_no)
                    pdf.savefig(fig)
                    plt.close(fig)

                page_no += 1
                fig = plt.figure(figsize=(PAGE_WIDTH, PAGE_HEIGHT))
                fig.patch.set_facecolor("white")
                y = TOP

            if kind == "h1":
                fig.text(LEFT, y, text, fontsize=H1_SIZE, fontweight="bold", va="top")
                y -= LINE_STEP * 1.8
            elif kind == "h2":
                fig.text(LEFT, y, text, fontsize=H2_SIZE, fontweight="bold", va="top")
                y -= LINE_STEP * 1.5
            elif kind == "code":
                fig.text(
                    LEFT + 0.02,
                    y,
                    text,
                    fontsize=9.5,
                    family="monospace",
                    va="top",
                    color="#222222",
                )
                y -= LINE_STEP
            else:
                fig.text(LEFT, y, text, fontsize=BODY_SIZE, va="top", color="#111111")
                y -= LINE_STEP

        if fig is not None:
            draw_header_footer(fig, page_no)
            pdf.savefig(fig)
            plt.close(fig)
    finally:
        pdf.close()


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = parse_markdown_lines(text)
    render_pdf(lines)
    print(f"Generated {OUTPUT}")
    print(f"Date: {date(2026, 7, 19).isoformat()}")


if __name__ == "__main__":
    main()
