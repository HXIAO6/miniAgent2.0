"""检索上下文安全过滤；与相关性评分分开，不向拒绝项回传原文。"""
from miniagent.security.injection import inspect_text
from miniagent.observability.decisions import audit


def filter_hits(policy, hits):
    """只返回允许片段的副本，保持原排序与字段。"""
    accepted = []
    for hit in hits:
        source = hit.get("source", "")
        codes = () if policy.permits_source(source) else ("source_denied",)
        if policy.scan_documents:
            codes += inspect_text("\n".join(str(hit.get(key, "")) for key in ("source", "location", "text")))
        if codes:
            audit("retrieval", "blocked", codes, source)
        else:
            accepted.append(dict(hit))
    return accepted
