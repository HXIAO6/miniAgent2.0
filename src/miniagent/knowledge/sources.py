"""资料名验证是共享规则，不依赖 Chroma 实例或界面。"""
from pathlib import Path
import re

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def validate_source(source: str):
    """删除只接受资料文件名，不接受路径、Windows 流名称或特殊目录。"""
    if (not isinstance(source, str) or not source or source in {".", ".."}
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', source)
            or source.endswith((" ", ".")) or Path(source).suffix.lower() not in SUPPORTED_EXTENSIONS):
        raise ValueError("非法资料文件名；只能删除知识库列表中的文档。")
