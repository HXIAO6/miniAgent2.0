"""文档管理用例；返回普通数据，不构造 Gradio 控件。"""
import asyncio
from pathlib import Path
from miniagent.config import logger
from miniagent.knowledge.ingest import ingest_file


class DocumentService:
    """复用既有入库、锁和回收站，数据位置和删除协议保持不变。"""

    def __init__(self, knowledge_base):
        self.knowledge_base = knowledge_base

    async def upload(self, files, chunk_chars=1200, overlap_chars=180):
        """显式注入知识库，避免默认全局实例绕开隔离测试上下文。"""
        if not files:
            return "请先选择资料文件。"
        def import_all():
            results = []
            for path in files:
                try:
                    results.append(ingest_file(path, self.knowledge_base, chunk_chars, overlap_chars))
                    logger.info("文档导入完成")
                except Exception as error:
                    logger.error("文档导入失败，类型=%s", type(error).__name__)
                    results.append(f"导入失败：{Path(path).name}：{error}")
            return "\n".join(results)
        return await asyncio.to_thread(import_all)

    async def snapshot(self):
        def read():
            with self.knowledge_base._lock:
                return self.knowledge_base.list_documents(), self.knowledge_base.status()
        return await asyncio.to_thread(read)

    async def delete(self, sources, confirmed=False):
        """业务层再次检查确认，避免其他入口直接绕过网页确认。"""
        if confirmed is not True:
            raise ValueError("删除文档需要明确确认。")
        def remove():
            messages = []
            for source in dict.fromkeys(sources):
                try:
                    result = self.knowledge_base.delete_document(source)
                    messages.append(f"已删除：{source}\n回收站：{result['trash_path']}")
                except Exception as error:
                    messages.append(f"未删除：{source}：{error}")
            return "\n\n".join(messages)
        return await asyncio.to_thread(remove)
