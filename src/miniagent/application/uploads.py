"""上传暂存服务：处理受限字节流，不依赖 FastAPI，也不修改用户原件。"""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import tempfile

from miniagent.knowledge.ingest import MAX_FILE_BYTES
from miniagent.knowledge.sources import validate_source


class UploadLimitError(ValueError):
    """上传资源上限错误，由 HTTP 层映射为 413。"""


@asynccontextmanager
async def staged_uploads(files, names, staging):
    """仅删除本次 mkdtemp 创建的目录，关闭上传句柄并保留正式知识库。"""
    for name in names:
        validate_source(name)
    staging.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="upload-", dir=staging))
    try:
        paths, total = [], 0
        for file, name in zip(files, names):
            path, size = temporary / name, 0
            with path.open("wb") as target:
                while block := await file.read(1024 * 1024):
                    size += len(block)
                    total += len(block)
                    if size > MAX_FILE_BYTES or total > 64 * 1024 * 1024:
                        raise UploadLimitError("单文件上限 30 MiB，一次上传总量上限 64 MiB。")
                    target.write(block)
            paths.append(path)
        yield paths
    finally:
        for file in files:
            await file.close()
        shutil.rmtree(temporary)
