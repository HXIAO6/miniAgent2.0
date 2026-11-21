# 第二阶段：LangChain 调用现有 DeepSeek 服务

目录已迁移到 `src/miniagent/`，顶层旧兼容模块已清理；当前结构见 [架构说明](architecture.md)。

## 已完成的边界

默认后端为 `langchain`，仍读取原有 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CHAT_MODEL` 和 `SUMMARY_MODEL`。
没有修改 `.env` 的密钥、地址或模型名称，也没有下载模型、修改原始资料、重建正式向量库或迁移聊天数据库。
旧 SDK 保留，设置 `CHAT_BACKEND=openai-agents` 并重启即可显式回退；不会在错误后自动调用另一个后端。

第二阶段没有实现自主知识库工具选择或完整安全图。知识库仍在生成前按原来的开关执行。
LangGraph 包由 LangChain Agent 的运行时需要而安装；自定义工作流属于第三阶段。
LangSmith 包属于依赖，本阶段使用 `tracing_context(enabled=False)` 禁止适配器自动远程追踪，未申请账号或上传资料。

## 通俗理解调用方式

LangChain 是 Python 库，不是一个需要单独打开的软件，也不是替代 DeepSeek 的模型。
`ChatOpenAI` 将普通消息列表转换成现有服务支持的 Chat Completions HTTP 请求。

```text
Gradio 输入
  → ChatRequest / chat_service
  → 原有 RAG：BGE-M3 + BM25 + RRF + ONNX
  → LangChainBackend
      → ChatOpenAI(model=原模型名, base_url=原地址, api_key=原密钥)
      → 原 DeepSeek 兼容接口
  → ModelEvent → ChatEvent → 页面与原 SQLite
```

`build_model()` 显式传递服务配置、超时及重试参数，并固定使用 Chat Completions，不要求服务支持 Responses API。
没有修改全局 Python、代理或系统环境变量。`http_socket_options=()` 保持 httpx 原有代理发现行为。

- 非流式：`await model.ainvoke(messages)`，用于摘要和兼容性检查。
- 流式：`async for chunk in model.astream(messages)`，把回答逐段转成 `ModelEvent`。
- 严格知识库模式：直接调用没有绑定工具的模型，程序保证不提供联网和文件工具。
- 普通工具模式：`StructuredTool.from_function()` 包装共享函数，`create_agent()` 处理唯一的工具循环。
- 摘要：超过 30 条消息时摘要旧内容、保留最近 8 条；新后端把摘要标为不可信历史数据，避免提升成系统指令。

## 重要文件

| 文件 | 职责 |
| --- | --- |
| `src/miniagent/adapters/llm.py` | 模型构建、Prompt 读取、摘要、流式输出及 LangChain Agent |
| `src/miniagent/tools/implementations.py` | 两个后端共用的四种工具 |
| `src/miniagent/prompts/answer.md` | 沿用原回答规则 |
| `src/miniagent/prompts/summarize.md` | 摘要规则及不可信历史说明 |
| `src/miniagent/contracts.py` | 请求与事件契约 |
| `src/miniagent/application/chat.py` | 将新旧模型事件转成统一格式，保留检索与引用逻辑 |
| `src/miniagent/config.py` | 后端、超时和重试配置 |
| `src/miniagent/cli/doctor.py` | 显示当前后端及依赖是否可用 |
| `tests/test_llm.py` | 本地模拟 HTTP 测试，验证真实 LangChain 解码与工具往返 |
| `tests/check_llm_compatibility.py` | 真实服务兼容性检查，仅使用合成资料和固定工具 |

文件工具沿用旧版项目范围限制，完整权限、审批和输出安全检查尚未实现。

## 本机环境与启动

当前统一使用用户指定的 Conda 环境 `miniAgent2.0`，实际路径为 `D:\.conda\envs\miniAgent2.0`。
第二阶段新增依赖已安装到该环境，复用其中已有依赖；pip 缓存使用 `D:\pip-cache`。
未修改全局或基础 Conda 环境。此前创建的独立实验环境停止使用。
删除旧 `D:\venvs\miniagent-phase2` 环境的操作被自动审批策略拒绝，该目录目前保留；新依赖已安装在指定的 Conda 环境中。

新机器仍可按 README 创建独立 `.venv` 并安装 `requirements.txt`；当前机器使用以下命令：

```powershell
Set-Location D:/miniAgent2.0
conda activate miniAgent2.0
python -m miniagent.cli.doctor
python -m miniagent
```

本机没有修改 VS Code 或全局解释器；启动时使用已激活的 `miniAgent2.0` 环境。
如需临时回退，另开终端设置后重启：

```powershell
$env:CHAT_BACKEND = "openai-agents"
python -m miniagent
```

已验证主要版本：LangChain 1.5.2、langchain-openai 1.8.5、langchain-core 1.8.4、LangGraph 1.2.24、LangSmith 0.16.0。
依赖安装前先 dry-run 检查，安装后 `pip check` 通过。未重复下载 embedding 或 ONNX 模型。

## 测试资料与结果

1. 完整回归：49 项全部通过，无跳过。资料包括原有六份虚构文档、七天更新为九天的入库样例、固定向量与安全样例，未使用个人知识库。
2. 新后端六项离线测试：合成 HTTP 流、固定工具时钟、32 条虚构历史、401、超时、取消、无证据拒答及配置切换通过；没有实际外网调用。
3. 真实模型普通调用：只发送“请回复兼容成功”，返回“兼容成功”。
4. 真实流式：合成资料“星舟设备冷却液每九天更换”，返回“周期是九天。[资料1]”，收到多个文本事件。
5. 真实摘要：32 条合成历史压缩为一条摘要加最近 8 条，正确保留九天的设定。
6. 真实工具调用：唯一工具为 `synthetic_clock`，返回固定 `2099-01-01 12:34:56`；模型实际调用并正确复述。没有执行文件或联网搜索工具。
7. 真实网页 + Ollama + ONNX + 新后端：仅导入“验证维护手册.md”，回答九天并附来源；无关的月球命名问题拒答；指定品牌问题明确说明资料未提供。
8. 旧 SDK 基线：原六份资料的 30 条检索排名、四种固定聊天结果和持久化消息数与第一阶段一致。

主要日志与 JSON 位于 `D:\miniAgent2.0-experiments\phase2/`：`tests.txt`、`llm-unit.txt`、`live-compatibility.json`、`live-ui.txt` 和 `legacy-baseline/`。
网页与原有回归测试的隔离库沿用 C 盘项目 `.cache/`，日志沿用 `data/logs/`；正式聊天路径在导入界面前通过测试环境变量切换为隔离路径。
本次生成请求只发送合成资料，成绩用于小规模兼容性验收，不能视为真实回答准确率或攻击防御效果。

## 下一阶段

确认本阶段体验后，再将知识库封装成受控工具、增加自主检索模式，并构建应用自己的 LangGraph 节点。
