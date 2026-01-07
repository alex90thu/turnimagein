import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from huggingface_hub import snapshot_download

# 下载整个模型仓库到当前目录下的 clip-ViT-B-32 文件夹
snapshot_download(
    repo_id="sentence-transformers/clip-ViT-B-32", 
    local_dir="./clip-ViT-B-32",
    local_dir_use_symlinks=False
)