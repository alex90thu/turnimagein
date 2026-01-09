#!/usr/bin/env python3
"""
PDF 配图页面提取工具
功能：
1. 扫描 PDF 文本层，寻找形如 "图11-7 标题..." 的图注。
2. 导出 CSV：包含图号、页码、完整标题。
3. 导出 PDF：仅包含有图注的页面，保持原文档画质。
4. 连续性自检：检查是否有中间遗漏的图号。
"""

import argparse
import csv
import os
import re
import sys
import fitz  # PyMuPDF
from collections import defaultdict

def clean_title(text):
    """清理标题中的换行符和多余空格"""
    # 替换换行符为空（针对中文排版，换行通常不加空格）
    text = text.replace('\n', '')
    text = text.replace('\r', '')
    return text.strip()

def check_continuity(figures):
    """检查图号连续性 (例如 11-1, 11-3 -> 警告缺 11-2)"""
    print("-" * 30)
    print("正在检查图号连续性...")
    
    # 按章节分组: data[chapter] = [index1, index2, ...]
    chapter_map = defaultdict(list)
    for item in figures:
        chapter_map[item['chapter']].append(item['index'])
    
    issues_found = False
    for chap, indices in sorted(chapter_map.items()):
        indices = sorted(list(set(indices))) # 去重并排序
        if not indices:
            continue
            
        # 检查是否从 1 开始（可选，有些书可能跨章）
        # if indices[0] != 1:
        #     print(f"[Warn] 第 {chap} 章图号不是从 1 开始，起始为: {chap}-{indices[0]}")
        
        # 检查中间断层
        for i in range(len(indices) - 1):
            curr = indices[i]
            next_val = indices[i+1]
            if next_val != curr + 1:
                missing = [f"{chap}-{x}" for x in range(curr + 1, next_val)]
                print(f"[警告] 第 {chap} 章可能缺失图号: {', '.join(missing)} (在 {chap}-{curr} 和 {chap}-{next_val} 之间)")
                issues_found = True
    
    if not issues_found:
        print("图号连续性检查通过。")
    print("-" * 30)

def extract_figures(pdf_path, output_dir=None):
    if not output_dir:
        output_dir = os.path.dirname(pdf_path) or "."
    
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    csv_path = os.path.join(output_dir, f"{base_name}_figures_index.csv")
    pdf_out_path = os.path.join(output_dir, f"{base_name}_figures_only.pdf")

    doc = fitz.open(pdf_path)
    print(f"正在扫描: {pdf_path} (共 {len(doc)} 页)...")

    # 正则表达式解释：
    # ^\s* : 必须是文本块的开头（忽略开头的少量空白），防止匹配到正文中的"如图xx所示"
    # 图        : 关键字
    # \s* : 可能的空白
    # (\d+)     : 章节号 (Group 1)
    # \s*[-–—]\s*: 连接符（连字符、短破折号等），允许周围有空格
    # (\d+)     : 索引号 (Group 2)
    # [\s\t\u3000]+ : 必须紧跟空格、制表符或全角空格 (关键分隔符)
    # (.*)      : 标题内容 (Group 3)
    pattern = re.compile(r'^\s*图\s*(\d+)\s*[-–—]\s*(\d+)[\s\t\u3000]+(.*)', re.DOTALL)

    extracted_data = []
    pages_to_keep = set()

    for page_num, page in enumerate(doc):
        # 获取文本块 (x0, y0, x1, y1, text, block_no, block_type)
        blocks = page.get_text("blocks")
        
        for b in blocks:
            block_text = b[4]
            match = pattern.match(block_text)
            if match:
                chapter_str = match.group(1)
                index_str = match.group(2)
                raw_title = match.group(3)
                
                # 拼接完整图号
                fig_id = f"图{chapter_str}-{index_str}"
                
                # 清洗标题
                clean_caption = clean_title(raw_title)
                
                # 记录数据
                extracted_data.append({
                    "fig_id": fig_id,
                    "chapter": int(chapter_str),
                    "index": int(index_str),
                    "page_index": page_num + 1, # 人类阅读的页码 (1-based)
                    "raw_page_index": page_num, # 0-based
                    "caption": clean_caption
                })
                
                pages_to_keep.add(page_num)

    if not extracted_data:
        print("未找到符合格式 '图XX-XX' 的配图页面。请检查正则或源文件。")
        return

    # 1. 导出 CSV
    print(f"找到 {len(extracted_data)} 个配图，涉及 {len(pages_to_keep)} 个页面。")
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Figure_ID", "Page", "Caption"])
        for item in extracted_data:
            writer.writerow([item["fig_id"], item["page_index"], item["caption"]])
    print(f"索引已保存: {csv_path}")

    # 2. 检查连续性
    check_continuity(extracted_data)

    # 3. 生成新的 PDF (仅提取页面)
    # 排序页面索引
    sorted_pages = sorted(list(pages_to_keep))
    
    new_doc = fitz.open()
    # insert_pdf 是无损的，直接从原 PDF 复制页面树
    new_doc.insert_pdf(doc, from_page=-1, to_page=-1, start_at=-1) #以此初始化，下面具体插入
    
    # 重新构建：仅插入需要的页面
    # 为了保持高效，我们创建一个新文档
    filtered_doc = fitz.open()
    # 批量插入非连续页面需要循环或构建 range，但在 PyMuPDF 中最快的方法是 load_page + insert_pdf
    # 或者使用 select 方法（但 select 是原地修改，我们想另存为）
    
    # 更高效的方法：复制原文档，然后保留指定页面
    # 但为了绝对安全不破坏原文件逻辑，我们用 insert_pdf
    filtered_doc.insert_pdf(doc, from_page=sorted_pages[0], to_page=sorted_pages[0])
    filtered_doc.delete_page(0) # 删除初始空页（如果有）
    
    # 这种方式对于大量非连续页面可能略慢，但最稳妥：
    for p_idx in sorted_pages:
        filtered_doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx)
        
    filtered_doc.save(pdf_out_path)
    print(f"提取版 PDF 已保存: {pdf_out_path}")

def main():
    parser = argparse.ArgumentParser(description="提取包含 '图XX-XX' 的页面并建立索引")
    parser.add_argument("pdf_path", help="PDF文件路径")
    parser.add_argument("-o", "--output", help="输出目录")
    
    args = parser.parse_args()
    
    extract_figures(args.pdf_path, args.output)

if __name__ == "__main__":
    main()