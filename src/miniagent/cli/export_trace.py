"""手动导出一个脱敏运行摘要；只传统计，不传 Prompt 或原文。"""
import argparse
import json
from pathlib import Path
from miniagent.observability.langsmith import export_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    arguments = parser.parse_args()
    try:
        export_summary(json.loads(arguments.summary.read_text(encoding="utf-8")))
    except Exception:
        # 不输出 SDK 响应及异常正文，避免凭据或内部地址进入终端日志。
        parser.exit(1, "导出失败：请检查摘要格式、导出开关、LangSmith 配置及网络。\n")
    print("摘要已提交至 LangSmith 项目 miniagent-sanitized。")


if __name__ == "__main__":
    main()
