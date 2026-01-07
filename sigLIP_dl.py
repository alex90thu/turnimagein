import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from huggingface_hub import snapshot_download

# 建议先试这个 base 版本，它比你现在的 CLIP-ViT-B-32 强不少
# 注意：路径名改为 siglip-base
snapshot_download(
    repo_id="mixedbread-ai/mxbai-embed-large-v1", # 这是一个基于 SigLIP 架构优化过的极强模型
    # 或者直接用官方：repo_id="google/siglip-base-patch16-256"
    local_dir="./siglip-model",
    local_dir_use_symlinks=False
)