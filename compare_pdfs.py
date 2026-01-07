#!/usr/bin/env python3
"""
优化版 PDF 配图查重 (Embedding + LLM)
功能：
1. 本地使用 CLIP 模型对所有页面图片进行 Embedding。
2. 计算向量相似度，快速召回（粗筛）可疑页面对。
3. 仅对高可疑对调用 Ollama 视觉大模型进行精排（验证）。
4. 结果存入 output/，日志存入 log/。
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
import torch
from typing import List, Dict

import fitz  # PyMuPDF
from PIL import Image
import requests
from sentence_transformers import SentenceTransformer, util

# --- 配置区域 ---
# Ollama 设置
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3-vl:235b"  # 请确保你的显存能跑动这个模型，跑不动请换 qwen2.5-vl:7b

# 本地 Embedding 模型 (首次运行会自动下载 ~300MB)
EMBEDDING_MODEL_NAME = "./clip-ViT-B-32"

# 路径设置 (支持相对路径或绝对路径)
BASE_OUTPUT_DIR = "output"
BASE_LOG_DIR = os.path.join(BASE_OUTPUT_DIR, "log")
# ----------------

# 初始化日志配置
def setup_logging():
    # 确保目录存在
    if not os.path.exists(BASE_LOG_DIR):
        os.makedirs(BASE_LOG_DIR)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_filename = os.path.join(BASE_LOG_DIR, f"run_{timestamp}.log")
    
    # 配置 Logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 文件处理器 (写入 log/)
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    # 控制台处理器 (输出到屏幕)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(message)s')) # 控制台只看简要信息
    logger.addHandler(console_handler)
    
    return logger, timestamp

logger = logging.getLogger() # 全局 logger 占位

def render_pdf_pages(pdf_path: str, zoom: float = 1.0) -> List[Dict]:
    """渲染 PDF 页面为图像"""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"无法打开 PDF: {pdf_path}, 错误: {e}")
        sys.exit(1)
        
    pages = []
    mat = fitz.Matrix(zoom, zoom)
    logger.info(f"正在解析 PDF: {pdf_path} (共 {len(doc)} 页)...")
    
    for i in range(len(doc)):
        try:
            page = doc[i]
            # 渲染页面
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes(output="png")
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            
            pages.append({
                "page_index": i + 1,
                "image": img,  # 用于 CLIP
                "b64": b64,    # 用于 Ollama
                "source": pdf_path
            })
        except Exception as e:
            logger.warning(f"页面 {i+1} 解析失败，跳过: {e}")
            
    return pages

def call_ollama_compare(b64_a: str, b64_b: str, timeout: int = 300) -> Dict:
    """调用大模型进行最终裁决"""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "判断两页中是否包含同一张配图/插图。忽略版面和文本，只看主要图片内容是否相同；"
                    "若相同 same=true，否则 false。必须输出合法 JSON：{\"same\": true, \"confidence\": 0.9, \"reason\": \"原因...\"}."
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
            # 简单的 JSON 提取逻辑
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end != -1:
                return json.loads(content[start:end])
            else:
                logger.warning(f"Ollama 返回了非 JSON 格式: {content[:100]}...")
    except requests.exceptions.ConnectionError:
        logger.error("连接 Ollama 失败，请确认 'ollama serve' 是否正在运行。")
        return {"same": False, "reason": "Connection Error", "confidence": 0.0}
    except Exception as e:
        logger.error(f"Ollama 调用异常: {e}")
        
    return {"same": False, "reason": "Model error", "confidence": 0.0}

def main():
    global logger
    logger, run_ts = setup_logging()
    
    parser = argparse.ArgumentParser(description="PDF 配图查重 (Embedding + LLM)")
    parser.add_argument("pdf1", help="源 PDF 路径")
    parser.add_argument("pdf2", help="目标 PDF 路径")
    parser.add_argument("--threshold", type=float, default=0.94, help="向量相似度阈值 (0-1)，默认 0.85")
    parser.add_argument("-o", "--output", default=None, help="指定输出文件名 (可选)")
    args = parser.parse_args()

    # 0. 准备输出目录
    if not os.path.exists(BASE_OUTPUT_DIR):
        os.makedirs(BASE_OUTPUT_DIR)

    # 1. 加载 Embedding 模型
    logger.info(f"正在加载 Embedding 模型: {EMBEDDING_MODEL_NAME} ...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device=device)
    except Exception as e:
        logger.error(f"加载 Embedding 模型失败: {e}")
        sys.exit(1)

    # 2. 提取图片
    pages1 = render_pdf_pages(args.pdf1)
    pages2 = render_pdf_pages(args.pdf2)
    
    if not pages1 or not pages2:
        logger.error("未提取到有效页面，程序终止。")
        sys.exit(0)

    # 3. 批量向量化 (Batch Embedding)
    logger.info(f"正在计算 PDF1 ({len(pages1)} 页) 的向量...")
    embeddings1 = embed_model.encode([p["image"] for p in pages1], convert_to_tensor=True)
    
    logger.info(f"正在计算 PDF2 ({len(pages2)} 页) 的向量...")
    embeddings2 = embed_model.encode([p["image"] for p in pages2], convert_to_tensor=True)

    # 4. 计算余弦相似度矩阵
    logger.info("计算向量相似度矩阵...")
    cosine_scores = util.cos_sim(embeddings1, embeddings2)

    # 5. 筛选候选集
    candidates = []
    for i in range(len(pages1)):
        for j in range(len(pages2)):
            score = cosine_scores[i][j].item()
            if score >= args.threshold:
                candidates.append({
                    "p1": pages1[i],
                    "p2": pages2[j],
                    "score": score
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"初步筛选: 发现 {len(candidates)} 对潜在相似页面 (阈值 > {args.threshold})")

    # 6. 对候选集进行 LLM 验证
    # 确定输出文件名
    if args.output:
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
            logger.info(f"[{idx}/{len(candidates)}] LLM 验证: P{p1['page_index']} <-> P{p2['page_index']} (Embedding分: {item['score']:.4f})")
            
            # 调用 Ollama
            llm_res = call_ollama_compare(p1["b64"], p2["b64"])
            
            # 如果 LLM 认为是同一张图，可以打印一条高亮日志
            if llm_res.get("same"):
                logger.info(f"    >>> 发现抄袭/相同: 置信度 {llm_res.get('confidence')}")

            writer.writerow([
                p1["page_index"],
                p2["page_index"],
                f"{item['score']:.4f}",
                llm_res.get("same"),
                llm_res.get("confidence"),
                llm_res.get("reason")
            ])
            f.flush()

    logger.info("任务完成。")

if __name__ == "__main__":
    main()