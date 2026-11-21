"""纯展示函数：消息 HTML、原文展开与候选表，不调用模型或数据库。"""
import html


def render_assistant_message(answer, thinking, elapsed_seconds, expanded):
    """生成回答内容：思考放在可展开的 details 区域，正式回答放在下面。"""
    total_seconds = max(0, int(elapsed_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    elapsed = f"{minutes} 分钟 {seconds} 秒" if minutes else f"{seconds} 秒"
    open_attribute = " open" if expanded else ""
    thinking_content = html.escape(thinking.strip() or "未返回思考内容。")
    return f"<details{open_attribute}>\n<summary>用时 {elapsed}</summary>\n\n{thinking_content}\n\n</details>\n\n{answer}"


def source_footer(hits: list[dict]) -> str:
    """来源标题直接来自索引元数据，并转义原文，避免模型编造来源或注入 HTML。"""
    import html
    if not hits:
        return ""
    lines = ["\n\n<!-- rag-sources -->\n---\n本次检索资料（具体依据见正文引用）："]
    for i, hit in enumerate(hits, 1):
        title = html.escape(f"[资料{i}] {hit['source']} · {hit['location']}")
        text = html.escape(hit["text"])
        scores = html.escape(score_description(hit))
        lines.append(f"<details><summary>{title}</summary><p>{scores}</p><pre>{text}</pre></details>")
    return "\n\n".join(lines)


def score_description(hit: dict) -> str:
    def show(key):
        value = hit.get(key)
        return "未入选该路候选" if value is None else f"{value:.4f}"
    return (f"向量相似度：{show('similarity')}；BM25：{show('bm25_score')}；"
            f"RRF：{show('rrf_score')}；重排：{show('rerank_score')}。这些分数不是答案正确率。")


def candidate_table(hits: list[dict], top_k: int, selected=None) -> list[list]:
    # 阈值可能让中间若干块被排除，引用编号必须按实际入选集合编号，不能按候选行号推算。
    selected = hits[:top_k] if selected is None else selected
    references = {hit["id"]: f"资料{i}" for i, hit in enumerate(selected, 1)}
    return [[i, references.get(hit["id"], "未送入回答"), hit["source"], hit["location"],
             hit.get("similarity"), hit.get("bm25_score"), hit.get("rrf_score"),
             hit.get("vector_rank"), hit.get("bm25_rank"), hit["text"][:180],
             hit.get("rerank_score"), hit.get("decision", ""), hit.get("rerank_windows")]
            for i, hit in enumerate(hits, 1)]
