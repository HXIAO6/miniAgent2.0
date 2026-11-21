"""项目统一配置：路径、模型和服务地址都从环境变量集中读取。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 包位于 src/miniagent；数据仍固定在原项目根目录，不随模块移动。
PROJECT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: Path) -> Path:
    path = Path(os.getenv(name) or default).expanduser()
    return (PROJECT_DIR / path).resolve() if not path.is_absolute() else path.resolve()


@dataclass(frozen=True)
class Settings:
    project_dir: Path = PROJECT_DIR
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    embedding_model: str = os.getenv("RAG_EMBED_MODEL", "bge-m3:latest")
    rerank_model_dir: Path = _path("RAG_RERANK_MODEL_DIR", PROJECT_DIR / "models" / "bge-reranker-base")
    chat_model: str = os.getenv("CHAT_MODEL", "deepseek-flash")
    summary_model: str = os.getenv("SUMMARY_MODEL") or os.getenv("CHAT_MODEL", "deepseek-flash")
    # 可显式切回旧 SDK；新后端失败时不自动重试另一后端，避免重复请求和工具副作用。
    chat_backend: str = os.getenv("CHAT_BACKEND", "langchain").strip().lower()
    model_timeout: float = float(os.getenv("MODEL_TIMEOUT", "60"))
    model_max_retries: int = int(os.getenv("MODEL_MAX_RETRIES", "1"))
    # 一轮自动知识库问答的工具调用和图步数上限，避免重复检索耗尽资源。
    agent_tool_limit: int = int(os.getenv("AGENT_TOOL_LIMIT", "3"))
    agent_recursion_limit: int = int(os.getenv("AGENT_RECURSION_LIMIT", "16"))
    openai_api_key: str = field(default=os.getenv("OPENAI_API_KEY", ""), repr=False)
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    tavily_api_key: str = field(default=os.getenv("TAVILY_API_KEY", ""), repr=False)
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "7860"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    strict_knowledge_default: bool = _bool("STRICT_KNOWLEDGE_DEFAULT", True)
    data_dir: Path = PROJECT_DIR / "data"
    knowledge_dir: Path = PROJECT_DIR / "knowledge"
    memory_db: Path = _path("MEMORY_DB_PATH", PROJECT_DIR / "data" / "memory.sqlite3")
    chroma_dir: Path = PROJECT_DIR / "data" / "chroma"
    log_file: Path = PROJECT_DIR / "data" / "logs" / "miniagent.log"


settings = Settings()


def configure_logging() -> logging.Logger:
    """同时写滚动文件和控制台；日志不记录问题正文、密钥或检索原文。"""
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("miniagent")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.log_file, maxBytes=5 * 1024 * 1024,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = configure_logging()
