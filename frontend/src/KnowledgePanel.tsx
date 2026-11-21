import { useEffect, useState } from "react";
import { api } from "./api";
import type { Document } from "./types";
import { KnowledgeMark } from "./components/KnowledgeMark";

export function KnowledgePanel({ disabled }: { disabled: boolean }) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [chunk, setChunk] = useState(1200);
  const [overlap, setOverlap] = useState(180);
  const refresh = async () => {
    try {
      const data = await api<{ documents: Document[] }>("/documents");
      setDocuments(data.documents); setSelected([]); setConfirmed(false);
    } catch (error) { setFeedback((error as Error).message); }
  };
  useEffect(() => { void refresh(); }, []);
  const upload = async () => {
    if (!files.length) return;
    setBusy(true); setFeedback("");
    try {
      const body = new FormData();
      files.forEach((file) => body.append("files", file));
      body.append("chunk_chars", String(chunk)); body.append("overlap_chars", String(overlap));
      const data = await api<{ result: string }>("/documents/upload", { method: "POST", body });
      setFeedback(data.result); setFiles([]); await refresh();
    } catch (error) { setFeedback((error as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true);
    try {
      const data = await api<{ result: string }>("/documents/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources: selected, confirmed }),
      });
      setFeedback(data.result); await refresh();
    } catch (error) { setFeedback((error as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="knowledge-panel">
    {/* 资料面板采用文件抽屉层级，空状态给出操作方向。 */}
    <div className="panel-heading"><div><h2>你的资料库</h2></div><button className="text-button" onClick={() => void refresh()} disabled={busy}>刷新</button></div>
    <p className="muted">文档留在本机，回答时仅将选中的片段发送给模型。</p>
    <label className="upload-area"><KnowledgeMark className="upload-symbol" /><strong>把资料放进来</strong><span>选择 TXT、Markdown 或文字版 PDF</span>
      <small>每份最多 30 MiB · 一次最多 8 份</small><input aria-label="上传资料" type="file" accept=".txt,.md,.pdf" multiple disabled={disabled || busy} onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
    </label>
    {files.length ? <p className="file-list">{files.map((file) => file.name).join("、")}</p> : null}
    <details className="advanced"><summary>分块设置</summary><div className="input-pair"><label>字符上限<input aria-label="分块字符数" type="number" min={200} max={4000} value={chunk} onChange={(event) => setChunk(Number(event.target.value))} /></label><label>重叠字符<input aria-label="重叠字符数" type="number" min={0} max={1999} value={overlap} onChange={(event) => setOverlap(Number(event.target.value))} /></label></div></details>
    <button className="primary-button wide" disabled={!files.length || disabled || busy} onClick={() => void upload()}>{busy ? "正在处理…" : "导入 / 更新资料"}</button>
    <div className="library-label">已入库文档 <span>{documents.length}</span></div>
    <div className="document-list">{documents.map((document) => <label className="document-row" key={document.source}>
      <input type="checkbox" disabled={disabled || busy} checked={selected.includes(document.source)} onChange={(event) => { setConfirmed(false); setSelected((previous) => event.target.checked ? [...previous, document.source] : previous.filter((item) => item !== document.source)); }} />
      <KnowledgeMark className="document-icon" /><span><strong>{document.source}</strong><small>{document.chunk_count} 个片段，{document.has_file ? "原文已保存" : "原文缺失"}</small></span>
    </label>)}</div>
    {!documents.length ? <div className="empty-library">资料库还是空的<br /><span>上传第一份文档，开始有据可查的对话。</span></div> : null}
    {selected.length ? <div className="delete-confirm"><p>待删除：{selected.join("、")}</p><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />已核对，确认移入回收站</label><button className="danger-button" disabled={!confirmed || disabled || busy} onClick={() => void remove()}>删除所选资料</button></div> : null}
    {feedback ? <pre className="feedback" role="status">{feedback}</pre> : null}
  </section>;
}
