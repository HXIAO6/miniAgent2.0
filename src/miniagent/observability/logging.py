"""日志初始化由启动入口显式调用，导入配置不创建日志目录或文件。"""
import logging
from logging.handlers import RotatingFileHandler
from miniagent.config import settings


def configure_logging(config=None) -> logging.Logger:
    """同时写滚动文件和控制台；日志不记录问题正文、密钥或检索原文。"""
    config = config or settings
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("miniagent")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(config.log_file, maxBytes=5 * 1024 * 1024,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
