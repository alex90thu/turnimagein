#!/usr/bin/env python3
"""比较两个 PDF 是否存在两页包含相同插图（使用本地 Ollama qwen3-vl:235b 进行可选验证）。

用法示例:
python compare_pdfs.py a.pdf b.pdf --verify

依赖：pymupdf、Pillow、imagehash、requests
"""
import argparse
import base64
import csv
import datetime
import io
import json
import os
import re
import sys
from typing import List, Dict, Optional, Tuple

import fitz
from PIL import Image
import requests
import imagehash

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3-vl:235b"


def render_pdf_pages(pdf_path: str, zoom: float = 2.0, compute_hash: bool = False) -> List[Dict]:
    doc = fitz.open(pdf_path)
    pages = []
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(doc)):
        page = doc[i]
        has_image = len(page.get_images(full=True)) > 0
        if not has_image:
            pages.append(
                {
                    "page_index": i + 1,
                    "image": None,
                    "hash": None,
                    "b64": None,
                    "raw": None,
                    "has_image": False,
                }
            )
            continue
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes(output="png")
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        ph = imagehash.phash(img) if compute_hash else None
        pages.append(
            {
                "page_index": i + 1,
                "image": img,
                "hash": ph,
                "b64": b64,
                "raw": img_bytes,
                "has_image": True,
            }
        )
    return pages


def find_candidate_pairs(
    pages1: List[Dict], pages2: List[Dict], max_hamming: int = 0
) -> List[Tuple[Dict, Dict, Optional[int]]]:
    pairs: List[Tuple[Dict, Dict, Optional[int]]] = []
    for p1 in pages1:
        for p2 in pages2:
            if p1["hash"] is None or p2["hash"] is None:
                pairs.append((p1, p2, None))
                continue
            dist = p1["hash"] - p2["hash"]
            if dist <= max_hamming:
                pairs.append((p1, p2, dist))
    return pairs


def call_ollama_compare(b64_a: str, b64_b: str, timeout: int = 300, debug: bool = False) -> Dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "判断两页中是否包含同一张配图/插图。忽略版面和文本，只看主要图片内容是否相同；"
                    "若相同 same=true，否则 false。只输出 JSON：{\"same\": true|false, \"confidence\": 0.0-1.0, \"reason\": \"...\"}."
                ),
                "images": [b64_a, b64_b],
            }
        ],
        "stream": False,
    }
    if debug:
        payload_preview = {
            "url": OLLAMA_URL,
            "model": OLLAMA_MODEL,
            "content_len": len(payload["messages"][0]["content"]),
            "images_count": len(payload["messages"][0]["images"]),
            "image_b64_lengths": [len(b64_a), len(b64_b)],
        }
        print("[DEBUG] request payload preview:", json.dumps(payload_preview, ensure_ascii=False))
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    except Exception as e:
        return {"error": f"request failed: {e}"}
    if debug:
        print("[DEBUG] status:", r.status_code)
        print("[DEBUG] headers:", {k: v for k, v in r.headers.items()})
        snippet = r.text[:800]
        print("[DEBUG] response text snippet:", snippet)
    if r.status_code != 200:
        return {"error": f"status {r.status_code}: {r.text}"}
    # Try to extract JSON from response text
    text = r.text
    try:
        data = r.json()
    except Exception:
        data = None
    if data and isinstance(data, dict):
        msg = data.get("message", {})
        text_fields = msg.get("content", "") or json.dumps(data)
    else:
        text_fields = text
    m = re.search(r"(\{\s*\"same\".*\})", text_fields, re.S)
    if not m:
        # fallback: find first {...}
        m2 = re.search(r"(\{.*\})", text_fields, re.S)
        if not m2:
            return {"error": "没有在模型返回中找到 JSON"}
        s = m2.group(1)
    else:
        s = m.group(1)
    try:
        j = json.loads(s)
        return {"result": j}
    except Exception as e:
        return {"error": f"解析 JSON 失败: {e}", "raw": s}


def main():
    parser = argparse.ArgumentParser(
        description="比较两个 PDF 是否有页面包含相同配图，默认直接让 Ollama 视觉模型判定"
    )
    parser.add_argument("pdf1")
    parser.add_argument("pdf2")
    parser.add_argument(
        "--hash-filter",
        action="store_true",
        help="先用 phash 过滤候选，再让模型判断（节省模型调用，可能漏检翻转/裁剪）",
    )
    parser.add_argument(
        "--max-hamming",
        type=int,
        default=5,
        help="phash 最大汉明距离，仅在 --hash-filter 时生效，默认 5",
    )
    parser.add_argument(
        "--limit-pairs",
        type=int,
        default=None,
        help="仅对前 N 个候选调用模型，调试用",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="打印请求与响应的调试信息（包含状态码和部分响应文本）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出 CSV 文件路径，未指定时自动生成 results-<timestamp>.csv",
    )
    args = parser.parse_args()

    print(f"渲染并提取：{args.pdf1} -> 页面图像")
    pages1 = render_pdf_pages(args.pdf1, compute_hash=args.hash_filter)
    print(f"共提取 {len(pages1)} 页")
    print(f"渲染并提取：{args.pdf2} -> 页面图像")
    pages2 = render_pdf_pages(args.pdf2, compute_hash=args.hash_filter)
    print(f"共提取 {len(pages2)} 页")

    pages1 = [p for p in pages1 if p.get("has_image")]
    pages2 = [p for p in pages2 if p.get("has_image")]

    if not pages1:
        print("源 PDF 无含配图页面，终止")
        sys.exit(0)
    if not pages2:
        print("目标 PDF 无含配图页面，终止")
        sys.exit(0)

    if args.hash_filter:
        candidates = find_candidate_pairs(pages1, pages2, max_hamming=args.max_hamming)
        if not candidates:
            print("未发现哈希匹配的页面对")
            sys.exit(0)
    else:
        candidates = [(p1, p2, None) for p1 in pages1 for p2 in pages2]

    if args.limit_pairs is not None:
        candidates = candidates[: args.limit_pairs]
        print(f"仅检测前 {len(candidates)} 个页面配对（limit-pairs 生效）")

    run_ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = args.output or f"results-{run_ts}.csv"

    results = []
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "page1", "page2", "same", "confidence", "reason"])
        f.flush()
        os.fsync(f.fileno())

        for idx, (p1, p2, dist) in enumerate(candidates, start=1):
            rec = {
                "page1": p1["page_index"],
                "page2": p2["page_index"],
                "hamming": int(dist) if dist is not None else None,
            }
            print(f"[{idx}/{len(candidates)}] 调用 Ollama 判定: 页面 {rec['page1']} vs {rec['page2']}")
            v = call_ollama_compare(p1["b64"], p2["b64"], debug=args.debug)
            rec.update(v)
            results.append(rec)

            res = rec.get("result") or {}
            writer.writerow(
                [
                    run_ts,
                    rec.get("page1"),
                    rec.get("page2"),
                    res.get("same"),
                    res.get("confidence"),
                    res.get("reason"),
                ]
            )
            f.flush()
            os.fsync(f.fileno())

    print("匹配结果:")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"CSV 已写入: {output_path}")


if __name__ == "__main__":
    main()
