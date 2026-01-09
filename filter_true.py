#!/usr/bin/env python3
import argparse
import csv
import os


def detect_same_col(header):
    keys = [h.strip().lower() for h in header]
    for cand in ("llm_same", "same", "result.same"):
        if cand in keys:
            return keys.index(cand)
    # fallback: try common position if header matches known format
    # timestamp, page1, page2, same, confidence, reason
    try:
        return keys.index("same")
    except ValueError:
        raise SystemExit("未在表头中找到 same/llm_same 列")


def parse_bool(v: str) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("true", "1", "yes")


def filter_file(path: str) -> str:
    base, ext = os.path.splitext(path)
    out = f"{base}_true{ext or '.csv'}"
    with open(path, "r", encoding="utf-8-sig", newline="") as fin, open(
        out, "w", encoding="utf-8", newline=""
    ) as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        try:
            header = next(reader)
        except StopIteration:
            raise SystemExit("输入 CSV 为空")
        writer.writerow(header)
        idx = detect_same_col(header)
        kept = 0
        for row in reader:
            if idx < len(row) and parse_bool(row[idx]):
                writer.writerow(row)
                kept += 1
    print(f"已写出: {out} (保留 {kept} 条)")
    return out


def main():
    ap = argparse.ArgumentParser(description="过滤出 same/llm_same 为 true 的 CSV 行")
    ap.add_argument("csv", help="待过滤的 CSV 文件路径")
    args = ap.parse_args()
    filter_file(args.csv)


if __name__ == "__main__":
    main()
