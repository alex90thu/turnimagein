import argparse
import csv
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract pages listed in a CSV column from a source PDF and write them"
            " to a new PDF in the same order."
        )
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        type=Path,
        default=Path("/data/lulab_commonspace/zhutong/comparePDFs/results_260109.csv"),
        help="Path to the input CSV file (default: latest comparePDFs results).",
    )
    parser.add_argument(
        "--pdf",
        dest="pdf_path",
        type=Path,
        default=Path(
            "/data/lulab_commonspace/zhutong/comparePDFs/ed4_figures_only_figures_only.pdf"
        ),
        help="Path to the source PDF to sample pages from (default: ED4 figures).",
    )
    parser.add_argument(
        "--column",
        dest="column",
        default="page2",
        help="CSV column name containing 1-based page numbers to extract.",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=Path,
        default=None,
        help=(
            "Path for the output PDF. Default is <csv_name>_<column>_pages.pdf next"
            " to the CSV file."
        ),
    )
    return parser.parse_args()


def read_pages(csv_path: Path, column: str) -> list[int]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    pages: list[int] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise ValueError(f"Column '{column}' not found in CSV header: {reader.fieldnames}")

        for idx, row in enumerate(reader, start=2):
            raw_value = (row.get(column) or "").strip()
            if not raw_value:
                continue
            try:
                pages.append(int(raw_value))
            except ValueError:
                print(f"Warning: invalid page number '{raw_value}' at CSV line {idx}; skipping.", file=sys.stderr)
    return pages


def extract_pages(pdf_path: Path, pages: list[int], output_path: Path) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()

    total = len(reader.pages)
    added = 0
    for page_num in pages:
        if page_num < 1 or page_num > total:
            print(
                f"Warning: page {page_num} out of range (1-{total}); skipping.",
                file=sys.stderr,
            )
            continue
        writer.add_page(reader.pages[page_num - 1])
        added += 1

    if added == 0:
        raise ValueError("No valid pages were added; nothing to write.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    return added


def main() -> None:
    args = parse_args()
    output_path = (
        args.output_path
        if args.output_path is not None
        else args.csv_path.with_name(f"{args.csv_path.stem}_{args.column}_pages.pdf")
    )

    try:
        pages = read_pages(args.csv_path, args.column)
        added = extract_pages(args.pdf_path, pages, output_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Wrote {added} pages from '{args.pdf_path}' to '{output_path}' using column '{args.column}'."
    )


if __name__ == "__main__":
    main()
