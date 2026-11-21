import { useEffect, useState } from "react";
import { Chat } from "./Chat";
import { SourcesPanel } from "./components/SourcesPanel";
import { SettingsPanel } from "./components/SettingsPanel";
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
        {tab === "sources" ? <SourcesPanel sources={sources} candidates={candidates} /> : null}
        {tab === "settings" ? <SettingsPanel options={chat.options} setOptions={chat.setOptions} running={chat.running} backend={backend} /> : null}
      </div>
    </aside>
  </div>;
}
