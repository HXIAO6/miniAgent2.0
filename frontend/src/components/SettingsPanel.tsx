import type { Dispatch, SetStateAction } from "react";
import type { Options } from "../types";

/** 设置面板只维护下一轮选项，不负责发送聊天。 */
export function SettingsPanel({ options, setOptions, running, backend }: { options: Options; setOptions: Dispatch<SetStateAction<Options>>; running: boolean; backend: string }) {
  return <section className="settings-panel"><p className="eyebrow">CONVERSATION SETTINGS</p><h2>回答方式</h2><p className="muted">设置作用于下一条问题，历史回答不变。</p>
          <label>调用模式<select aria-label="调用模式" value={options.mode} disabled={running} onChange={(event) => setOptions({ ...options, mode: event.target.value as typeof options.mode })}><option value="forced">强制检索知识库</option><option value="auto" disabled={backend !== "langchain"}>Agent 自动决定</option><option value="chat">普通聊天</option></select></label>
          <p className="setting-help">自动模式只提供知识库工具；普通聊天仅开放服务端白名单工具。强制模式可在无依据时直接拒答。</p>
          <label className="checkbox-setting"><input type="checkbox" checked={options.only_knowledge} disabled={running || options.mode !== "forced"} onChange={(event) => setOptions({ ...options, only_knowledge: event.target.checked })} />仅依据知识库回答</label>
          <label>检索方式<select aria-label="检索方式" value={options.retrieval_mode} disabled={running} onChange={(event) => setOptions({ ...options, retrieval_mode: event.target.value as typeof options.retrieval_mode })}><option value="hybrid">混合检索（推荐）</option><option value="vector">仅向量检索</option><option value="bm25">仅 BM25</option></select></label>
          <label className="checkbox-setting"><input type="checkbox" checked={options.use_rerank} disabled={running} onChange={(event) => setOptions({ ...options, use_rerank: event.target.checked })} />本地重排与阈值过滤</label>
          {([['top_k', '最多引用片段', 1, 10, 1], ['candidate_k', '每路候选数', 10, 60, 5], ['rerank_k', '最多重排候选', 10, 40, 5], ['rerank_threshold', '重排最低分数', 0, 1, .01]] as const).map(([key, title, min, max, step]) => <label key={key}>{title}<input aria-label={title} type="number" min={min} max={max} step={step} value={options[key]} disabled={running} onChange={(event) => setOptions({ ...options, [key]: Number(event.target.value) })} /></label>)}
          <div className="privacy-note">◈ 来源分数表示相关性，不是正确率。请结合原文核对结论。</div>
        </section>;
}
