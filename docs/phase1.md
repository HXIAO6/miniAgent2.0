# 第一阶段：基线与聊天服务抽取

本文保留第一阶段实施记录。后续清理已移除顶层兼容脚本，当前入口与路径以 [架构说明](architecture.md) 为准。

## 范围

本阶段复用 OpenAI Agents SDK 和原有模型配置，不引入 LangChain、LangGraph 或 LangSmith。
保留原有解析、分块、混合检索、ONNX 重排和 SQLite 格式；不重建或写入正式知识库。

## 新的调用关系

```text
Gradio predict / predict_with_scores
    → ChatRequest
    → chat_service.stream_chat(request, dependencies)
        → 现有 knowledge_base.retrieve
        → 现有摘要函数、Agent 与 Runner
        → ChatEvent
    → 原有引用与 HTML 渲染
    → 原有 SQLite 保存函数
```

- `src/contracts.py`：定义请求、依赖和事件。事件包含回答、状态、来源、候选和保存标记。
- `src/chat_service.py`：执行检索、严格模式拒答、旧 SDK 流式调用及引用编号检查，不导入 Gradio。
- `src/knowledge_assistant.py`：保留工具与旧 SDK 定义、页面、存储和网页 API；聊天回调改为事件适配。
- `tests/test_chat_service.py`：用固定输出验证引用、拒答、历史清理、普通聊天、错误、取消及快照。
- `tests/smoke_chat_service.py`：通过真实 Gradio API 验证回答、引用、候选表、拒答及 SQLite 保存，不调用外部模型。
- `tests/security/`：验证已有的来源转义及严格模式禁用工具边界。
- `evaluations/datasets/security_cases.json`：合成攻击、正常安全教学文本及事实投毒样例。
- `evaluations/baseline.py`：创建隔离临时库，对比三种检索模式和四类固定输出聊天场景。

事件的 `history` 保持旧历史输入兼容；`answer` 不包含新生成的来源 HTML，调用方负责渲染。
服务事件的 `persist` 表示本轮已经结束，由入口保存。取消请求不会被当作普通错误吞掉。
本阶段尚未把工具、摘要和所有展示函数完全拆分，后续继续按模型适配和权限边界迁移。

## 如何运行基线

在仓库根目录，用已有项目解释器执行：

```powershell
python -B evaluations/baseline.py --output-dir D:\miniAgent2.0-experiments\phase1
python -B evaluations/baseline.py --output-dir D:\miniAgent2.0-experiments\phase1 --compare "已有报告的完整路径"
python -B tests/smoke_chat_service.py
```

脚本仅使用合成资料；向量为确定性哈希词袋，生成结果为固定 SDK 事件，不调用外部模型服务。
报告记录数据集和核心模块 SHA256、依赖版本、三路检索排名、回答、引用、模型调用次数与消息数。
旧阶段曾使用仓库外的入口副本进行对照；当前基线脚本统一使用正式包，不再提供 `--legacy-entry`。
报告应留在忽略目录或 D 盘实验目录，不提交带个人数据的运行产物。

这些指标只验证流程兼容性，不能作为 BGE-M3 语义质量、真实回答准确率或攻击成功率。
事实投毒样例只提供将来的评测标签，本阶段没有新增事实核验或注入检测器。

## 验收分工

开发代理负责自动化验收：回归测试、前后基线比较、语法检查、隔离网页接口验证。
用户负责最终体验确认：启动页面后检查导入、提问、引用展开和已有聊天记录是否符合预期。
真实 Ollama / DeepSeek 联调单独记录；服务不可用时明确标为未验证，不以固定输出测试代替。
离线聊天网页验证使用本机 7863 端口，实验报告保存在项目 `.cache/chat-ui-smoke-*/report.json`。

第一阶段通过后仍需先确认，再实施第二阶段模型适配。

## 本次自动化验收结果

- 改造前：35 项测试，28 项通过，7 项真实 Ollama 集成测试因离线模式跳过。
- 改造后：43 项测试，36 项通过，同样跳过 7 项 Ollama 集成测试。
- 新旧入口对照：30 条检索记录（三种模式 × 十个问题）、四种固定输出聊天场景及八条持久化消息一致。
- 真实 Gradio API：文档列表、删除确认、回收站及候选清理通过；聊天回答、引用、候选表、无证据拒答和 SQLite 保存通过。
- 真实 Ollama / DeepSeek 问答未运行：本机 Ollama 端口当前拒绝连接；本次没有发送外部生成请求。
- 已有依赖环境仍有事件循环未关闭的 ResourceWarning，未影响本次测试通过。

主报告和新旧测试日志位于 `D:\miniAgent2.0-experiments\phase1/`。
旧入口副本只保存在该实验目录中，用于对照，不加入仓库。
现有回归和网页脚本沿用项目 `.cache/`，配置模块沿用 `data/logs/`，这些本机产物不提交。
测试通过环境变量和临时库隔离历史及知识库；原有检索、入库、重排和记忆模块内容哈希保持一致。

### Ollama 启动后的补充验收

上述未验证状态已通过本次补测更新：

- 确认本机 Ollama 可访问，已有 `bge-m3:latest`，未下载或更换模型。
- 完整测试 43 项全部通过，无跳过，包含真实 embedding、增量更新及 ONNX 重排。
- 真实检索评估：向量、BM25、混合检索的平均预期来源召回率均为 1.0；MRR 分别为 1.0、0.9375、1.0。
- 重排校准仍选择 0.20。校准集保留 8/8 个有依据问题，拒绝 1/2 个无答案问题；保留验证集保留 6/6 个有依据问题，拒绝 2/2 个无答案问题。
- 真实网页、Ollama、ONNX 及当前配置生成服务联调通过：回答九天并附引用；无相关证据时拒答；部分有依据时回答周期并明确品牌未提供。
- 小规模合成集的结果不代表真实资料正确率；校准集仍有一个无答案问题未被阈值拒绝。

补测日志：`D:\miniAgent2.0-experiments\phase1/` 下的 `ollama-tests.txt`、`ollama-retrieval.txt`、`ollama-rerank.txt` 和 `live-smoke.txt`。
真实检索与重排 JSON 报告沿用项目 `.cache/retrieval-evaluation-*/` 和 `.cache/rerank-evaluation-*/`。
测试全程使用隔离库，未修改正式原文、向量库和聊天数据库。
测试资料全文见 [合成测试资料](synthetic-data.md)。
