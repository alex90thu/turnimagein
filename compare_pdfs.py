#!/usr/bin/env python3
"""
PDF 配图查重 (SigLIP Native Version) - ModelScope 适配版
修复日志路径问题：强制清理根 Logger，只将日志输出到 /output/log 和 控制台。
"""
import argparse
import base64
import csv
import datetime
import io
import json
import logging
import os
import sys
from typing import List, Dict

import fitz  # PyMuPDF
from PIL import Image
import requests
import torch
from transformers import AutoProcessor, AutoModel

# --- 配置区域 ---
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3-vl:235b" 

# [修改] 指向你从 ModelScope 下载的模型文件夹绝对路径
# 例如: /home/guozehua/models/google_siglip-so400m-patch14-384
VISION_MODEL_NAME = "/data/guozehua/modelscope/models/google/siglip-so400m-patch14-384"

# 路径设置
BASE_OUTPUT_DIR = "output"
# 确保日志只在 output/log 下
BASE_LOG_DIR = os.path.join(BASE_OUTPUT_DIR, "log")
# ----------------

def setup_logging():
    # 1. 确保目录存在
    if not os.path.exists(BASE_LOG_DIR):
        os.makedirs(BASE_LOG_DIR)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_filename = os.path.join(BASE_LOG_DIR, f"run_{timestamp}.log")
    
    # 2. 获取根 Logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # [核心修复] 清理掉所有可能已经存在的 Handlers (防止某些库偷偷往根目录写日志)
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # 3. 添加文件 Handler (写入 output/log/...)
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    # 4. 添加控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(console_handler)
    
    # 抑制 transformers 库本身的冗余日志
    logging.getLogger("transformers").setLevel(logging.ERROR)
    
    return logger, timestamp

# 初始化一个空对象，稍后在 main 中赋值
logger = logging.getLogger()

def render_page_without_text(page, zoom: float = 1.0):
    """内存中克隆页面并涂白文字"""
    text_blocks = page.get_text("blocks")
    shape = page.new_shape()
    for block in text_blocks:
        rect = fitz.Rect(block[:4])
        shape.draw_rect(rect)
        shape.finish(color=None, fill=(1, 1, 1))
    shape.commit()
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix

def render_pdf_pages(pdf_path: str, zoom: float = 1.0) -> List[Dict]:
    """渲染 PDF 页面为图像（已去除文字）"""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"无法打开 PDF: {pdf_path}, 错误: {e}")
        sys.exit(1)
        
    pages = []
    logger.info(f"正在解析并去除文字干扰: {pdf_path} (共 {len(doc)} 页)...")
    
    for i in range(len(doc)):
        try:
            page = doc[i]
            pix = render_page_without_text(page, zoom=zoom)
            img_bytes = pix.tobytes(output="png")
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            
            # 过滤纯白页
            extrema = img.convert("L").getextrema()
            if extrema == (255, 255): 
                continue

            pages.append({
                "page_index": i + 1,
                "image": img,  
                "b64": b64,    
                "source": pdf_path
            })
        except Exception as e:
            logger.warning(f"页面 {i+1} 解析失败，跳过: {e}")
            
    logger.info(f"解析完成，保留了 {len(pages)} 个含图页面。")
    return pages

def get_siglip_embeddings(model, processor, images: List[Image.Image], batch_size=32, device="cpu"):
    """使用 SigLIP 生成图像向量 (带 Batch 处理)"""
    all_embeddings = []
    model.eval()
    
    total = len(images)
    for i in range(0, total, batch_size):
        batch = images[i : i + batch_size]
        try:
            inputs = processor(images=batch, return_tensors="pt").to(device)
            with torch.no_grad():
                image_features = model.get_image_features(**inputs)
                # 归一化特征
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                all_embeddings.append(image_features.cpu())
        except Exception as e:
            logger.error(f"Embedding 计算出错 (Batch {i}): {e}")
            sys.exit(1)
            
    if not all_embeddings:
        return torch.tensor([])
    return torch.cat(all_embeddings)

def call_ollama_compare(b64_a: str, b64_b: str, timeout: int = 300) -> Dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Look at these two images (text masked). "
                    "Determine if the visible figures/diagrams are fundamentally the same. "
                    "Return JSON: {\"same\": boolean, \"confidence\": float(0-1), \"reason\": string}."
                ),
                "images": [b64_a, b64_b],
            }
        ],
        "stream": False,
        "options": {"temperature": 0.1}
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        if r.status_code == 200:
            res_json = r.json()
            content = res_json.get("message", {}).get("content", "")
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end != -1:
                return json.loads(content[start:end])
    except Exception as e:
        logger.error(f"Ollama Error: {e}")
    return {"same": False, "reason": "Error", "confidence": 0.0}

def main():
    global logger
    logger, run_ts = setup_logging()
    
    parser = argparse.ArgumentParser(description="PDF 配图查重 (Native SigLIP + 去字版)")
    parser.add_argument("pdf1")
    parser.add_argument("pdf2")
    parser.add_argument("--threshold", type=float, default=0.7, help="相似度阈值")
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--skip-csv", dest="skip_csv", default=None, help="包含需跳过的 (page1,page2) 组合的CSV文件")
    args = parser.parse_args()

    # 加载模型
    logger.info(f"加载 SigLIP 模型: {VISION_MODEL_NAME} ...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    try:
        processor = AutoProcessor.from_pretrained(VISION_MODEL_NAME)
        model = AutoModel.from_pretrained(VISION_MODEL_NAME).to(device)
    except Exception as e:
        logger.error(f"加载模型失败: {e}")
        logger.error("请检查路径，或者运行: pip install -U transformers torch")
        sys.exit(1)

    # 提取并计算
    pages1 = render_pdf_pages(args.pdf1)
    pages2 = render_pdf_pages(args.pdf2)
    
    if not pages1 or not pages2:
        logger.error("未找到含有图片的页面。")
        sys.exit(0)

    logger.info(f"正在计算 PDF1 向量 (Size: {len(pages1)})...")
    embeddings1 = get_siglip_embeddings(model, processor, [p["image"] for p in pages1], device=device)
    
    logger.info(f"正在计算 PDF2 向量 (Size: {len(pages2)})...")
    embeddings2 = get_siglip_embeddings(model, processor, [p["image"] for p in pages2], device=device)

    logger.info("计算相似度矩阵...")
    cosine_scores = torch.mm(embeddings1, embeddings2.t())

    # 读取跳过组合
    skip_pairs = set()
    if args.skip_csv:
        try:
            with open(args.skip_csv, "r", encoding="utf-8") as sf:
                reader = csv.DictReader(sf)
                if reader.fieldnames and ("page1" in reader.fieldnames and "page2" in reader.fieldnames):
                    for row in reader:
                        try:
                            p1 = int(row["page1"]) if row["page1"] != "" else None
                            p2 = int(row["page2"]) if row["page2"] != "" else None
                            if p1 is not None and p2 is not None:
                                skip_pairs.add((p1, p2))
                        except Exception:
                            continue
                else:
                    logger.warning(f"跳过CSV不含期望的列名 page1/page2: {args.skip_csv}")
            logger.info(f"从跳过CSV载入 {len(skip_pairs)} 个组合，将直接跳过对应候选。")
        except FileNotFoundError:
            logger.warning(f"未找到跳过CSV: {args.skip_csv}，将忽略该参数。")
        except Exception as e:
            logger.warning(f"读取跳过CSV失败: {e}，将忽略该参数。")

    candidates = []
    for i in range(len(pages1)):
        for j in range(len(pages2)):
            score = cosine_scores[i][j].item()
            if score >= args.threshold:
                p1_idx = pages1[i]["page_index"]
                p2_idx = pages2[j]["page_index"]
                if (p1_idx, p2_idx) in skip_pairs:
                    # 直接跳过，不进入候选，不做LLM
                    continue
                candidates.append({
                    "p1": pages1[i],
                    "p2": pages2[j],
                    "score": score
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"发现 {len(candidates)} 对高相似候选 (Threshold > {args.threshold})")

    # 确定输出文件路径
    if args.output:
        # 如果用户指定了 -o filename.csv，则存放在 output/filename.csv
        # 如果用户指定了完整路径，则不做处理，但建议只指定文件名
        if os.path.dirname(args.output):
             csv_filename = args.output
        else:
             csv_filename = os.path.join(BASE_OUTPUT_DIR, args.output)
    else:
        csv_filename = os.path.join(BASE_OUTPUT_DIR, f"results_{run_ts}.csv")
    
    logger.info(f"结果将写入: {csv_filename}")
    
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page1", "page2", "sim_score", "llm_same", "confidence", "reason"])

        for idx, item in enumerate(candidates, 1):
            p1 = item["p1"]
            p2 = item["p2"]
            logger.info(f"[{idx}/{len(candidates)}] LLM 验证: P{p1['page_index']} <-> P{p2['page_index']} (SigLIP Score: {item['score']:.4f})")
            
            llm_res = call_ollama_compare(p1["b64"], p2["b64"])
            
            if llm_res.get("same"):
                logger.info(f"    >>> 发现相同: {llm_res.get('confidence')}")

            writer.writerow([
                p1["page_index"],
                p2["page_index"],
                f"{item['score']:.4f}",
                llm_res.get("same"),
                llm_res.get("confidence"),
                llm_res.get("reason")
            ])
            f.flush()

    logger.info("Done.")

if __name__ == "__main__":
    main()