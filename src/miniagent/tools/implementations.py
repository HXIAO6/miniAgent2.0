"""供两个后端复用的原有工具实现；此阶段不扩大文件权限或新增工具。"""
import datetime
import os
from tavily import TavilyClient

from miniagent.config import settings

ALLOWED_DIR = os.path.normcase(os.path.realpath(str(settings.project_dir)))


def get_current_time() -> str:
    """查询本机当前日期与时间。"""
    return datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")

def search_web(query: str) -> str:
    """联网搜索最新信息，并把搜索摘要交给模型。"""
    if not settings.tavily_api_key:
        return "联网搜索未配置，请在 .env 中设置 TAVILY_API_KEY。"
    try:
        # 延迟创建客户端，普通时间查询和严格知识库问答不需要联网搜索配置。
        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(query=query, search_depth="basic", max_results=3)
        results = response.get("results", [])
        if not results:
            return "没有搜到相关结果。"
        return "".join(
            f"[网络{index + 1}] 标题: {item.get('title')}\n链接: {item.get('url')}\n内容摘要: {item.get('content')}\n\n"
            for index, item in enumerate(results)
        )
    except Exception as error:
        return f"搜索失败: {error}"

def is_safe_path(file_path: str) -> bool:
    """只允许访问项目目录，防止工具读写项目外的文件。"""
    try:
        target_path = os.path.normcase(os.path.realpath(file_path))
        return os.path.commonpath([ALLOWED_DIR, target_path]) == ALLOWED_DIR
    except (OSError, ValueError):
        return False

def read_local_file(file_path: str) -> str:
    """读取项目目录内不超过 500 KiB 的 UTF-8 文本文件。"""
    if not is_safe_path(file_path):
        return "权限拒绝！"
    try:
        if os.path.getsize(file_path) > 500 * 1024:
            return "文件太大，拒绝读取。"
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as error:
        return f"读取失败: {error}"

def write_local_file(file_path: str, content: str) -> str:
    """将文本保存到项目目录内的指定文件，沿用旧版路径检查。"""
    if not is_safe_path(file_path):
        return "权限拒绝！"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        return f"成功：内容已成功写入文件 '{file_path}'。"
    except Exception as error:
        return f"写入失败: {error}"
