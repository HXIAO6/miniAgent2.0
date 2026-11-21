import type { RunEvent } from "./types";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : `请求失败（${response.status}）`);
  }
  return response.json();
}

/** 按 SSE 帧解码；网络分块可能切在中文 UTF-8 字节或事件分隔符中间。 */
export async function consumeEvents(response: Response, onEvent: (event: RunEvent) => void) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "无法开始回答。");
  }
  if (!response.body) throw new Error("浏览器未提供流式响应。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  const parse = (frame: string) => {
    const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
    if (!data) return;
    const event = JSON.parse(data) as RunEvent;
    if (["run.completed", "run.failed", "run.cancelled"].includes(event.type)) terminal = true;
    onEvent(event);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // 服务端固定 LF，兼容反向代理转换的 CRLF。
      buffer = buffer.replaceAll("\r\n", "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        parse(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
    if (buffer.trim()) parse(buffer);
    if (!terminal) throw new Error("连接中断，回答可能未完成。请刷新历史确认状态。");
  } finally {
    reader.releaseLock();
  }
}
