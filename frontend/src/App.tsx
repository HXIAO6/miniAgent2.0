import { useEffect, useState } from "react";
import { Chat } from "./Chat";
import { KnowledgePanel } from "./KnowledgePanel";
import { api } from "./api";
import { useChat } from "./useChat";
import type { Source } from "./types";

export default function App() {
  const chat = useChat();
  const [tab, setTab] = useState<"library" | "sources" | "settings">("library");
  const [sources, setSources] = useState<Source[]>([]);
  const [candidates, setCandidates] = useState<Source[]>([]);
  const [model, setModel] = useState("");
  const [backend, setBackend] = useState("");
  // 来源属于当前会话，切换或新建会话时清理上一次查看的片段。
  useEffect(() => { setSources([]); setCandidates([]); }, [chat.threadId, chat.legacy]);
  useEffect(() => { void api<{ model: string; backend: string }>("/health").then((health) => { setModel(health.model); setBackend(health.backend); }).catch(() => {}); }, []);
  const inspect = (selected: Source[], all: Source[]) => { setSources(selected); setCandidates(all); setTab("sources"); };
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="MiniAgent 首页"><span className="brand-mark">m</span><span>miniagent<span className="brand-version">个人知识空间</span></span></a>
      <button className="new-chat" disabled={chat.running} onClick={() => void chat.newThread()}><span>＋</span>新建对话 <kbd>↗</kbd></button>
      <div className="nav-heading">对话记录</div>
      <nav className="thread-list" aria-label="对话列表">{chat.threads.map((thread) => <button key={thread.id} disabled={chat.running} className={chat.threadId === thread.id ? "thread-item active" : "thread-item"} onClick={() => { setSources([]); void chat.selectThread(thread.id); }}><span>◷</span><span>{thread.title}</span></button>)}</nav>
      <div className="sidebar-footer"><button onClick={() => void chat.showLegacy()} disabled={chat.running}>▤ 查看旧版聊天 <span>只读</span></button><div className="local-badge"><i />本机知识库<span>PERSONAL</span></div></div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><div><span className="workspace-label">知识助手</span><span className="topbar-divider">/</span><span className="thread-title">{chat.legacy ? "旧版聊天记录" : chat.threads.find((thread) => thread.id === chat.threadId)?.title ?? "新对话"}</span></div>
        <div className="topbar-actions"><span className="model-pill"><i />{model || "连接模型中"}</span><button title="删除当前会话" aria-label="删除当前会话" onClick={() => void chat.deleteThread()} disabled={!chat.threadId || chat.running}>⌫</button></div></header>
      {chat.error ? <div className="error-banner" role="alert">{chat.error}</div> : null}
      <Chat key={chat.legacy ? "legacy" : chat.threadId ?? "loading"} chat={chat} inspect={inspect} />
    </main>
    <aside className="inspector"><div className="panel-tabs" role="tablist">{([['library', '资料库'], ['sources', '来源'], ['settings', '设置']] as const).map(([key, title]) => <button role="tab" aria-selected={tab === key} key={key} className={tab === key ? "selected" : ""} onClick={() => setTab(key)}>{title}</button>)}</div>
      <div className="inspector-content">
        {tab === "library" ? <KnowledgePanel disabled={chat.running} /> : null}
        {tab === "sources" ? <section className="sources-panel"><p className="eyebrow">EVIDENCE & CONTEXT</p><h2>回答的依据</h2><p className="muted">点击回答下的来源，查看本轮引用的原文。</p>
          {!sources.length ? <div className="empty-library">暂未选择来源</div> : sources.map((source, index) => <article className="source-card" key={source.id}><span className="source-number">资料 {index + 1}</span><h3>{source.source}</h3><small>{source.location}</small><pre>{source.text}</pre><p>重排分数：{source.rerank_score?.toFixed(3) ?? "未启用"}</p></article>)}
          {candidates.length ? <details className="candidate-details"><summary>查看 {candidates.length} 个候选片段</summary>{candidates.map((source) => <div key={source.id}><strong>{source.source}</strong><p>{source.decision ?? "候选"} · {source.rerank_score?.toFixed(3) ?? "—"}</p><pre>{source.text}</pre></div>)}</details> : null}
        </section> : null}
        {tab === "settings" ? <section className="settings-panel"><p className="eyebrow">CONVERSATION SETTINGS</p><h2>回答方式</h2><p className="muted">设置作用于下一条问题，历史回答不变。</p>
          <label>调用模式<select aria-label="调用模式" value={chat.options.mode} disabled={chat.running} onChange={(event) => chat.setOptions({ ...chat.options, mode: event.target.value as typeof chat.options.mode })}><option value="forced">强制检索知识库</option><option value="auto" disabled={backend !== "langchain"}>Agent 自动决定</option><option value="chat">普通聊天</option></select></label>
          <p className="setting-help">自动模式只提供知识库工具；普通聊天仅开放服务端白名单工具。强制模式可在无依据时直接拒答。</p>
          <label className="checkbox-setting"><input type="checkbox" checked={chat.options.only_knowledge} disabled={chat.running || chat.options.mode !== "forced"} onChange={(event) => chat.setOptions({ ...chat.options, only_knowledge: event.target.checked })} />仅依据知识库回答</label>
          <label>检索方式<select aria-label="检索方式" value={chat.options.retrieval_mode} disabled={chat.running} onChange={(event) => chat.setOptions({ ...chat.options, retrieval_mode: event.target.value as typeof chat.options.retrieval_mode })}><option value="hybrid">混合检索（推荐）</option><option value="vector">仅向量检索</option><option value="bm25">仅 BM25</option></select></label>
          <label className="checkbox-setting"><input type="checkbox" checked={chat.options.use_rerank} disabled={chat.running} onChange={(event) => chat.setOptions({ ...chat.options, use_rerank: event.target.checked })} />本地重排与阈值过滤</label>
          {([['top_k', '最多引用片段', 1, 10, 1], ['candidate_k', '每路候选数', 10, 60, 5], ['rerank_k', '最多重排候选', 10, 40, 5], ['rerank_threshold', '重排最低分数', 0, 1, .01]] as const).map(([key, title, min, max, step]) => <label key={key}>{title}<input aria-label={title} type="number" min={min} max={max} step={step} value={chat.options[key]} disabled={chat.running} onChange={(event) => chat.setOptions({ ...chat.options, [key]: Number(event.target.value) })} /></label>)}
          <div className="privacy-note">◈ 来源分数表示相关性，不是正确率。请结合原文核对结论。</div>
        </section> : null}
      </div>
    </aside>
  </div>;
}
