# compare_pdfs

这个小工具用于比较两个 PDF 中的页面是否含有相同的配图/插图。默认直接把每个页面对发送给本地 Ollama 视觉模型 `qwen-vl:235b`（127.0.0.1:11434）进行判定，可选用 `phash` 先做快速过滤以减少模型调用。

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

运行示例（默认直接用模型对所有含配图的页面配对判定，并写出 CSV，文件名自动带时间戳）：

```bash
python compare_pdfs.py a.pdf b.pdf
```

说明：
- `--hash-filter`：先用 `phash` 过滤候选，再让模型判定（可减少模型调用，可能漏检翻转/裁剪）。
- `--max-hamming`：配合 `--hash-filter` 使用，默认 5。
- `--limit-pairs`：仅检查前 N 个候选（调试用）。
- 默认会对所有页面配对调用模型，请确保本地 `ollama serve` 已启动且模型可用。
- 在比较前会跳过不含配图的页面。
- 输出 CSV 列顺序：timestamp, page1, page2, same, confidence, reason。每个页面配对完成后立刻追加写入，避免中途异常导致数据丢失。默认文件名类似 `results-20260106T130000.csv`，可用 `-o` 自定义。
