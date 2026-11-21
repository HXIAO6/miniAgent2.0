"""默认启动 FastAPI + assistant-ui；旧 Gradio 通过独立命令继续保留。"""
from miniagent.api.app import launch

if __name__ == "__main__":
    launch()
