import type { Source } from "../types";

/** 来源展示只接收本轮数据，不读取会话或请求接口。 */
export function SourcesPanel({ sources, candidates }: { sources: Source[]; candidates: Source[] }) {
  return <section className="sources-panel"><p className="eyebrow">EVIDENCE & CONTEXT</p><h2>回答的依据</h2><p className="muted">点击回答下的来源，查看本轮引用的原文。</p>
          {!sources.length ? <div className="empty-library">暂未选择来源</div> : sources.map((source, index) => <article className="source-card" key={source.id}><span className="source-number">资料 {index + 1}</span><h3>{source.source}</h3><small>{source.location}</small><pre>{source.text}</pre><p>重排分数：{source.rerank_score?.toFixed(3) ?? "未启用"}</p></article>)}
          {candidates.length ? <details className="candidate-details"><summary>查看 {candidates.length} 个候选片段</summary>{candidates.map((source) => <div key={source.id}><strong>{source.source}</strong><p>{source.decision ?? "候选"} · {source.rerank_score?.toFixed(3) ?? "—"}</p><pre>{source.text}</pre></div>)}</details> : null}
        </section>;
}
