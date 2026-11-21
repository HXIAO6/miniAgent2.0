"""模型引用数据序列化；不包含界面 HTML。"""
import json


def evidence_json(hits: list[dict]) -> str:
    """只给模型已选中的原文与来源，不把候选分数包装成可信度。"""
    return json.dumps([{
        "citation": f"资料{i}", "source": h["source"],
        "location": h["location"], "text": h["text"],
    } for i, h in enumerate(hits, 1)], ensure_ascii=False)
