import { createContext, useContext } from "react";
import {
  AssistantRuntimeProvider, ComposerPrimitive, MessagePrimitive,
  ThreadPrimitive, useExternalStoreRuntime, useAuiState, type AppendMessage, type ThreadMessageLike,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import type { Message, Source } from "./types";
import type { useChat } from "./useChat";

const MessageData = createContext<{ messages: Message[]; inspect: (sources: Source[], candidates: Source[]) => void }>({
  messages: [], inspect: () => {},
});

function MarkdownText() {
  return <MarkdownTextPrimitive />;
}

function UserMessage() {
  return <MessagePrimitive.Root className="message user-message"><div className="user-bubble"><MessagePrimitive.Parts /></div></MessagePrimitive.Root>;
}

function AssistantMessage() {
  const data = useContext(MessageData);
  return <MessagePrimitive.Root className="message assistant-message">
    <span className="assistant-avatar" aria-hidden="true">m</span>
    <div className="answer-body">
      <div className="message-byline">MiniAgent <span>知识助手</span></div>
      <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
      <MessagePrimitive.If hasContent={false}><span className="thinking">正在准备回答…</span></MessagePrimitive.If>
      <MessageDetails messages={data.messages} inspect={data.inspect} />
    </div>
  </MessagePrimitive.Root>;
}

function MessageDetails({ messages, inspect }: { messages: Message[]; inspect: (sources: Source[], candidates: Source[]) => void }) {
  // assistant-ui 的消息选择器与后端消息 ID 一致，不按数组位置猜测所属消息。
  const id = useAuiState((state) => state.message.id);
  const message = messages.find((item) => item.id === id);
  if (!message) return null;
  const metadata = message.metadata;
  const sources = metadata.sources ?? [];
  return <div className="message-details">
    {metadata.tools?.length ? <div className="tool-events">{metadata.tools.map((tool, index) =>
      <span key={`${index}-${tool.type}`}>{tool.type === "tool.completed" ? "✓" : "↳"} {tool.name === "search_knowledge" ? "检索个人知识库" : tool.name}</span>)}</div> : null}
    {sources.length ? <div className="source-chips">{sources.map((source, index) =>
      <button key={source.id} onClick={() => inspect(sources, metadata.candidates ?? [])}>[{index + 1}] {source.source} <span>↗</span></button>)}</div> : null}
    {metadata.status_text ? <details className="run-details"><summary>执行过程{metadata.elapsed_seconds ? ` · ${Math.round(metadata.elapsed_seconds)} 秒` : ""}</summary><pre>{metadata.status_text}</pre></details> : null}
    {metadata.status === "cancelled" || metadata.status === "interrupted" ? <p className="message-warning">已停止 · 当前内容可能不完整</p> : null}
    {metadata.status === "failed" ? <p className="message-warning">{metadata.error ?? "本轮运行失败，可重新发送问题。"}</p> : null}
  </div>;
}

export function Chat({ chat, inspect }: { chat: ReturnType<typeof useChat>; inspect: (sources: Source[], candidates: Source[]) => void }) {
  const convertMessage = (message: Message): ThreadMessageLike => ({
    id: message.id, role: message.role, content: message.content || "",
    ...(message.role === "assistant" ? { status:
      message.metadata.status === "running" ? { type: "running" as const } :
      ["failed", "cancelled", "interrupted"].includes(message.metadata.status ?? "")
        ? { type: "incomplete" as const, reason: message.metadata.status === "failed" ? "error" as const : "cancelled" as const }
        : { type: "complete" as const, reason: "stop" as const },
    } : {}),
    metadata: { runId: message.metadata.run_id, custom: message.metadata },
  });
  const runtime = useExternalStoreRuntime<Message>({
    messages: chat.messages, convertMessage, isRunning: chat.running,
    isDisabled: chat.legacy || chat.loading, activeRunId: chat.activeRunId,
    onNew: async (message: AppendMessage) => {
      const text = message.content.filter((part) => part.type === "text").map((part) => part.text).join("\n");
      await chat.send(text);
    },
    onCancel: chat.cancel,
  });
  return <MessageData.Provider value={{ messages: chat.messages, inspect }}>
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="thread">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty>
            <div className="welcome"><div className="welcome-icon">m<span>✦</span></div>
              <p className="eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</p><h1>让资料，成为答案。</h1>
              <p>从你的文档出发，获得有据可查的回答。</p>
              <div className="suggestions">{["总结我的资料中最重要的内容", "根据我的手册，整理操作步骤", "比较资料中的不同观点"].map((text) =>
                <button key={text} disabled={chat.loading || chat.legacy} onClick={() => void chat.send(text)}>{text}<span>↗</span></button>)}</div>
            </div>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </ThreadPrimitive.Viewport>
        {chat.legacy ? <div className="readonly-notice">旧版聊天只读展示，原数据库未修改。新建对话即可继续。</div> :
          <ComposerPrimitive.Root className="composer">
            <ComposerPrimitive.Input placeholder="向你的知识库提问…" aria-label="输入问题" className="composer-input" />
            <div className="composer-bottom"><span><i /> {chat.options.mode === "auto" ? "Agent 自动检索" : chat.options.mode === "forced" ? "知识库优先" : "普通对话"}</span>
              {chat.running ? <ComposerPrimitive.Cancel className="send-button" aria-label="停止生成">■</ComposerPrimitive.Cancel> :
                <ComposerPrimitive.Send className="send-button" aria-label="发送消息">↑</ComposerPrimitive.Send>}
            </div>
          </ComposerPrimitive.Root>}
        <p className="composer-note">检索在本机完成 · 回答内容会发送至已配置的模型服务 · 请核对来源</p>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  </MessageData.Provider>;
}
