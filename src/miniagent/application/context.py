"""历史内容归一化，不依赖界面或模型框架。"""
import ast


def message_content_to_text(content):
    """把字符串、字典或 Gradio 文本块列表统一转换成普通字符串。"""
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("[") and "'text'" in stripped:
            try:
                return message_content_to_text(ast.literal_eval(stripped))
            except (SyntaxError, ValueError):
                pass
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return message_content_to_text(content["text"])
        if isinstance(content.get("content"), str):
            return message_content_to_text(content["content"])
        return ""
    if isinstance(content, (list, tuple)):
        return "".join(message_content_to_text(item) for item in content)
    return str(content) if content is not None else ""
