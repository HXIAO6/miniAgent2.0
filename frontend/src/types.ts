/** 前后端事件边界：模型消息和来源均为数据，前端不执行后端 HTML。 */
export type Source = {
  id: string; source: string; location: string; text: string;
  rerank_score?: number; similarity?: number; decision?: string;
};
export type Message = {
  id: string; role: "user" | "assistant"; content: string;
  metadata: {
    status?: string; run_id?: string; status_text?: string; error?: string;
    sources?: Source[]; candidates?: Source[];
    tools?: { type: string; name: string }[]; elapsed_seconds?: number; legacy?: boolean;
  };
};
export type Thread = { id: string; title: string; updated_at: string };
export type Document = { source: string; chunk_count: number; has_file: boolean };
export type Options = {
  mode: "forced" | "auto" | "chat"; only_knowledge: boolean;
  top_k: number; candidate_k: number; retrieval_mode: "hybrid" | "vector" | "bm25";
  use_rerank: boolean; rerank_threshold: number; rerank_k: number;
};
export type RunEvent = {
  type: string; seq: number; run_id: string; thread_id: string; message_id: string;
  data: { text?: string; name?: string; status?: string; sources?: Source[];
    candidates?: Source[]; message?: Message; error?: string };
};
