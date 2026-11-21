"""文档解析、分块与参数验证，不访问向量库或生成模型。"""
from pathlib import Path
import re

CHUNK_CHARS = 1200
OVERLAP_CHARS = 180


def extract_sections(path: Path) -> list[tuple[str, str]]:
    """按可追溯位置提取文字。PDF 使用文件页序号；Markdown 保留标题与行范围。"""
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ValueError("PDF 解析需要 pypdf；当前可先上传 TXT 或 Markdown。") from error
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请先提供未加密副本。")
        sections = [(f"PDF 文件第 {i} 页", page.extract_text() or "")
                    for i, page in enumerate(reader.pages, 1)]
    else:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError as error:
                raise ValueError("无法识别文本编码，请另存为 UTF-8。") from error
        sections = []
        heading = "正文"
        buffer = []
        first_line = 1
        for line_number, line in enumerate(text.splitlines(), 1):
            if path.suffix.lower() == ".md" and re.match(r"^#{1,6}\s+", line):
                if buffer:
                    sections.append((f"{heading}；第 {first_line}–{line_number - 1} 行", "\n".join(buffer)))
                heading = re.sub(r"^#{1,6}\s+", "", line).strip()
                buffer, first_line = [], line_number
            buffer.append(line)
        if buffer:
            sections.append((f"{heading}；第 {first_line}–{len(text.splitlines())} 行", "\n".join(buffer)))
    if not any(text.strip() for _, text in sections):
        raise ValueError("文档没有可提取的文字；扫描 PDF 需要先进行 OCR。")
    return sections


def validate_chunk_settings(chunk_chars: int, overlap_chars: int) -> tuple[int, int]:
    """分块参数同时用于前端和命令行，统一校验以避免大量重复块。"""
    chunk_chars, overlap_chars = int(chunk_chars), int(overlap_chars)
    if not 200 <= chunk_chars <= 4000:
        raise ValueError("每块大小必须在 200–4000 字符之间。")
    if not 0 <= overlap_chars < chunk_chars // 2:
        raise ValueError("重叠大小必须非负且小于每块大小的一半。")
    return chunk_chars, overlap_chars


def make_chunks(sections: list[tuple[str, str]], chunk_chars: int = CHUNK_CHARS,
                overlap_chars: int = OVERLAP_CHARS) -> list[dict]:
    # 尽量在换行处断开；保留重叠，使跨边界的事实仍有机会完整出现在某一块里。
    chunk_chars, overlap_chars = validate_chunk_settings(chunk_chars, overlap_chars)
    chunks = []
    for location, text in sections:
        start = 0
        while start < len(text):
            end = min(start + chunk_chars, len(text))
            if end < len(text):
                boundary = text.rfind("\n", start + chunk_chars // 2, end)
                if boundary >= 0:
                    end = boundary + 1
            content = text[start:end].strip()
            if content:
                chunks.append({"text": content,
                               "location": f"{location}；节内字符 {start + 1}–{end}"})
            if end == len(text):
                break
            start = max(start + 1, end - overlap_chars)
    return chunks
