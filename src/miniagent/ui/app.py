"""只负责创建 Gradio 控件和绑定回调，不在导入时初始化页面。"""
import os
from pathlib import Path
from miniagent.config import settings
from miniagent.knowledge.rag import DEFAULT_RERANK_THRESHOLD


def create_app(handlers=None):
    """由入口显式创建页面；上传缓存配置先于 Gradio 的实际使用。"""
    os.environ["GRADIO_TEMP_DIR"] = str(settings.project_dir / ".cache" / "gradio")
    import gradio as gr
    if handlers is None:
        from miniagent.ui import handlers
    with gr.Blocks(title="本地知识库助手") as demo:
        gr.Markdown("# 🤖 本地知识库助手")
        gr.Markdown("上传资料后提问，回答附来源与原文。检索在本机完成，命中的片段会发送给当前配置的大模型服务。")
        with gr.Accordion("知识库管理", open=True, elem_classes="module-panel"):
            files = gr.File(label="选择资料（TXT、Markdown、文字版 PDF）", file_count="multiple",
                            file_types=[".txt", ".md", ".pdf"], type="filepath")
            gr.Markdown("单文件上限 30 MiB。同名文件作为同一文档更新，旧原文件保留在 knowledge/.versions 中。扫描 PDF 请先做 OCR。")
            with gr.Row():
                chunk_chars = gr.Slider(200, 4000, value=1200, step=100, label="每块最多字符数")
                overlap_chars = gr.Slider(0, 1000, value=180, step=20, label="相邻块重叠字符数")
            gr.Markdown("重叠须小于块大小的一半。修改分块设置后，重新导入同一资料即可重新索引。")
            import_button = gr.Button("导入 / 更新资料", variant="primary")
            import_status = gr.Textbox(label="导入结果", interactive=False)
            refresh_button = gr.Button("刷新文档列表与状态")
            kb_status = gr.Textbox(label="知识库状态", interactive=False)
            documents_table = gr.Dataframe(headers=["文档", "文本块数", "原文件"],
                                           datatype=["str", "number", "str"], interactive=False,
                                           label="知识库文档（含原文缺失的残留索引）")
            delete_sources = gr.Dropdown(choices=[], value=[], multiselect=True, label="选择要从知识库删除的文档")
            deletion_preview = gr.Textbox(label="待删除清单", interactive=False)
            delete_confirmed = gr.Checkbox(value=False, label="我已核对文件，确认删除并移入回收站")
            delete_button = gr.Button("删除所选文档", variant="stop")
            deletion_status = gr.Textbox(label="删除结果", interactive=False)
        use_knowledge = gr.Checkbox(value=True, label="优先检索知识库（普通闲聊时可关闭）")
        only_knowledge = gr.Checkbox(value=settings.strict_knowledge_default, label="仅依据知识库回答（无依据时直接说明；关闭联网和文件工具）")
        knowledge_mode = gr.Dropdown(choices=[("强制知识库检索（原行为）", "forced"),
                                              ("Agent 自动决定是否检索", "auto")],
                                     value="forced", label="知识库调用模式")
        gr.Markdown("自动模式需启用知识库，仅开放知识库查询工具，由模型决定是否查询；“仅依据知识库回答”开关适用于强制模式。关闭知识库则为原普通聊天。")
        with gr.Accordion("检索设置与候选分数", open=False, elem_classes="module-panel"):
            retrieval_mode = gr.Dropdown(choices=[("混合检索（推荐）", "hybrid"),
                                                 ("仅向量检索", "vector"), ("仅关键词 BM25", "bm25")],
                                         value="hybrid", label="检索方式")
            with gr.Row():
                top_k = gr.Slider(1, 10, value=4, step=1, label="最多送入回答的片段数")
                candidate_k = gr.Slider(10, 60, value=20, step=5, label="每路召回候选数")
            use_rerank = gr.Checkbox(value=True, label="启用本地重排与阈值过滤")
            with gr.Row():
                rerank_threshold = gr.Slider(0, 1, value=DEFAULT_RERANK_THRESHOLD, step=0.01, label="重排最低分数")
                rerank_k = gr.Slider(10, 40, value=20, step=5, label="最多重排候选数")
            gr.Markdown("先混合召回，再重排与过滤。重排分数不是正确率；阈值越高越容易拒答，也可能漏掉有效资料。关闭重排时阈值不生效。参考原文总长最多 12000 字符。")
            scores = gr.Dataframe(headers=["当前名次", "回答引用", "文档", "位置", "向量相似度",
                                           "BM25 分数", "RRF 分数", "向量名次", "BM25 名次", "原文预览", "重排分数", "筛选结果", "评分窗口数"],
                                  datatype=["number", "str", "str", "str", "number", "number", "number", "number", "number", "str", "number", "str", "number"],
                                  interactive=False, label="最近一次提问的检索候选")
        # 历史在浏览器打开页面时加载，创建 Blocks 本身不读写聊天数据库。
        chatbot = gr.Chatbot(height=600, value=[], elem_classes="chat-panel")
        gr.Markdown("## 💬 输入问题")
        # 单行模式让 Enter 触发 submit；Shift+Enter 仍可换行，CSS 保留输入区高度。
        # 内置发送按钮与 Enter 共用下方的 submit 事件，避免两套处理逻辑。
        msg = gr.Textbox(placeholder="请输入问题，Enter 发送，Shift+Enter 换行…",
                         label="问题", lines=1, max_lines=8, submit_btn="发送",
                         elem_classes="question-input")
        with gr.Row(elem_classes="clear-chat-row"):
            clear = gr.Button("清空聊天", variant="secondary", scale=0, min_width=150)
        msg.submit(handlers.predict_with_scores, [msg, chatbot, use_knowledge, top_k, candidate_k, retrieval_mode,
                                       use_rerank, rerank_threshold, rerank_k, only_knowledge, knowledge_mode],
                   [msg, chatbot, scores], concurrency_limit=1, concurrency_id="knowledge_operations")
        clear.click(handlers.clear_history, None, [chatbot, msg], queue=False)
        # 导入、删除和整轮聊天共用一个队列，避免正在生成的回答与删除操作交错。
        panel_outputs = [documents_table, delete_sources, kb_status, delete_confirmed, deletion_preview, scores]
        import_button.click(handlers.upload_documents, [files, chunk_chars, overlap_chars], [import_status],
                            concurrency_limit=1, concurrency_id="knowledge_operations").then(
                                handlers.refresh_document_panel, None, panel_outputs)
        refresh_button.click(handlers.refresh_document_panel, None, panel_outputs)
        delete_sources.change(handlers.preview_deletion, [delete_sources], [deletion_preview, delete_confirmed], queue=False)
        delete_button.click(handlers.delete_documents, [delete_sources, delete_confirmed], [deletion_status, *panel_outputs],
                            concurrency_limit=1, concurrency_id="knowledge_operations")
        demo.load(handlers.refresh_document_panel, None, panel_outputs)
        demo.load(handlers.load_history, None, [chatbot])
    
    return demo


def launch():
    """统一启动入口，自检不改变现有知识库或模型配置。"""
    import gradio as gr
    from miniagent.cli.doctor import run_startup_checks, format_startup_checks
    from miniagent.config import logger, configure_logging
    configure_logging(settings)
    css = (Path(__file__).parent / "assets" / "styles.css").read_text(encoding="utf-8")
    logger.info("\n%s", format_startup_checks(run_startup_checks()))
    demo = create_app()
    demo.launch(server_name=settings.host, server_port=settings.port, inbrowser=True,
                theme=gr.themes.Soft(), css=css)
