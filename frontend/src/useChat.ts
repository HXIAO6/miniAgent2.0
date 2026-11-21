import { useCallback, useEffect, useRef, useState } from "react";
import { api, consumeEvents } from "./api";
import type { Message, Options, RunEvent, Thread } from "./types";

export const defaultOptions: Options = {
  mode: "forced", only_knowledge: true, top_k: 4, candidate_k: 20,
  retrieval_mode: "hybrid", use_rerank: true, rerank_threshold: .2, rerank_k: 20,
};

export function useChat() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [options, setOptions] = useState(defaultOptions);
  const [legacy, setLegacy] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string>();
  const request = useRef<{ id: string; abort: AbortController } | null>(null);
  const mounted = useRef(true);

  const refreshThreads = useCallback(async () => {
    const data = await api<{ threads: Thread[] }>("/threads");
    if (mounted.current) setThreads(data.threads);
    return data.threads;
  }, []);

  const selectThread = useCallback(async (id: string) => {
    if (request.current) return;
    setLoading(true); setError(""); setLegacy(false);
    try {
      const data = await api<{ messages: Message[] }>(`/threads/${id}/messages`);
      setMessages(data.messages); setThreadId(id);
      localStorage.setItem("miniagent.thread", id);
    } catch (failure) { setError((failure as Error).message); }
    finally { setLoading(false); }
  }, []);

  const newThread = useCallback(async () => {
    if (request.current) return;
    setError("");
    try {
      const thread = await api<Thread>("/threads", { method: "POST" });
      await refreshThreads(); await selectThread(thread.id);
    } catch (failure) { setError((failure as Error).message); }
  }, [refreshThreads, selectThread]);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const list = await refreshThreads();
        const previous = localStorage.getItem("miniagent.thread");
        if (list.length) await selectThread(list.find((thread) => thread.id === previous)?.id ?? list[0].id);
        else await newThread();
      } catch (failure) { setError((failure as Error).message); }
      finally { setLoading(false); }
    })();
    return () => {
      mounted.current = false;
      const active = request.current;
      if (active) {
        void fetch(`/api/runs/${active.id}/cancel`, { method: "POST", keepalive: true });
        active.abort.abort();
      }
    };
  }, [refreshThreads, selectThread, newThread]);

  const send = async (text: string) => {
    if (!threadId || request.current || legacy || !text.trim()) return;
    const id = crypto.randomUUID();
    const abort = new AbortController();
    request.current = { id, abort };
    setActiveRunId(id); setRunning(true); setError("");
    const optimistic = `pending-${id}`;
    setMessages((items) => [...items,
      { id: `user-${id}`, role: "user", content: text, metadata: {} },
      { id: optimistic, role: "assistant", content: "", metadata: { status: "running", run_id: id } },
    ]);
    let sequence = 0;
    try {
      const response = await fetch(`/api/threads/${threadId}/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: id, message: text, options }), signal: abort.signal,
      });
      await consumeEvents(response, (event: RunEvent) => {
        // 明确绑定运行及序号，取消后晚到的事件不改写另一个会话。
        if (event.run_id !== id || event.seq <= sequence || request.current?.id !== id) return;
        sequence = event.seq;
        setMessages((items) => items.map((message) => {
          if (message.id !== optimistic && message.id !== event.message_id) return message;
          const next: Message = { ...message, id: event.message_id, metadata: { ...message.metadata } };
          if (event.type === "message.delta") next.content += event.data.text ?? "";
          if (event.type === "message.replace") next.content = event.data.text ?? "";
          if (event.type === "run.status") next.metadata.status_text = event.data.text;
          if (event.type === "retrieval.completed") {
            next.metadata.sources = event.data.sources; next.metadata.candidates = event.data.candidates;
          }
          if (event.type.startsWith("tool.")) next.metadata.tools = [
            ...(next.metadata.tools ?? []), { type: event.type, name: event.data.name ?? "工具" },
          ];
          if (event.data.message) return event.data.message;
          if (event.type === "run.failed") { next.metadata.status = "failed"; next.metadata.error = event.data.error; }
          return next;
        }));
      });
    } catch (failure) {
      if ((failure as Error).name !== "AbortError") setError((failure as Error).message);
    } finally {
      // 重新读取后端结果，网络失败/重复请求也不留下浏览器自造的历史。
      request.current = null;
      if (mounted.current) {
        setRunning(false);
        try {
          const data = await api<{ messages: Message[] }>(`/threads/${threadId}/messages`);
          setMessages(data.messages); await refreshThreads();
        } catch (failure) { setError((failure as Error).message); }
      }
    }
  };

  const cancel = async () => {
    const active = request.current;
    if (!active) return;
    try { await api(`/runs/${active.id}/cancel`, { method: "POST" }); }
    catch (failure) { setError((failure as Error).message); }
    finally { active.abort.abort(); }
  };

  const showLegacy = async () => {
    if (running) return;
    try {
      const data = await api<{ messages: Message[] }>("/legacy/messages");
      setMessages(data.messages); setLegacy(true); setThreadId(null); setError("");
    } catch (failure) { setError((failure as Error).message); }
  };

  const deleteThread = async () => {
    if (!threadId || running || !window.confirm("确认删除这个会话？知识库资料不受影响。")) return;
    try {
      await api(`/threads/${threadId}`, { method: "DELETE" });
      const list = await refreshThreads();
      if (list.length) await selectThread(list[0].id); else await newThread();
    } catch (failure) { setError((failure as Error).message); }
  };
  return { threads, threadId, messages, running, loading, error, options, setOptions,
    legacy, activeRunId, send, cancel, newThread, selectThread, showLegacy, deleteThread };
}
