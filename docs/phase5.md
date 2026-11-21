# 第五阶段：脱敏运行摘要与可复现实验

本阶段增加两种能力：知道每轮聊天运行了多久、用了什么工具、在哪里被安全策略阻止；保存数据集与代码版本，以便比较不同版本的实验结果。保留原模型服务、向量库、聊天库和工具权限，不增加第三方依赖。

## 怎么理解 LangSmith

LangChain 负责调用模型和工具，LangGraph 组织流程，LangSmith 类似远程运行看板。但直接开启框架自动追踪通常会采集 Prompt、工具参数和回答，个人知识库不适合默认这样做。

这里采用**本地统计 + 手动导出统计摘要**。框架原有 `tracing_context(enabled=False)` 保留，LangSmith SDK 已经在指定环境中，无需另外下载。它不是完整模型调用树，也不包含 token、费用或逐节点耗时，本阶段不宣称完成这些能力。

## 新增与修改

| 文件 | 输入与输出 |
| --- | --- |
| `observability/tracing.py` | 应用事件 → 每轮独立 JSON；记录状态、耗时、工具次数、候选/入选数量和安全决策计数 |
| `observability/langsmith.py` | 本地摘要 → 固定字段白名单 → LangSmith create_run；未知字段丢弃 |
| `cli/export_trace.py` | 单个摘要文件路径 → 显式手动导出 |
| `cli/evaluate.py` | 合成集 → 独立实验目录、manifest、报告；两个相同数据集报告 → 指标差值 |
| `application/chat.py` | 包裹原流程事件，不改变模型/检索/生成逻辑 |
| `security/policy.py` | 原安全日志同时累计当前请求的脱敏决策次数 |
| `config.py`、`.env.example`、`cli/doctor.py` | 追踪路径、开关和自检 |
| `tests/test_observability.py` | 合成事件、假密钥、模拟 LangSmith 客户端测试 |
| `.github/workflows/ci.yml` | 原回归外增加离线实验及 GitHub artifact |

本地摘要明确不含：用户问题、回答、聊天历史、文档名称、文档内容、工具参数、模型地址、配置密钥、异常详情和原始推理。安全计数表示检查决策次数，同一片段多处复查可能累计多次，不能当作独立攻击数。

正常、拒答、失败与取消均有终态；收到终态的消费者可以直接停止，摘要已经先保存。文件写入失败只警告，不使聊天失败。进程被强杀或断电时不保证保存当前摘要。每次使用 UUID 独立文件，不修改历史记录，不自动清理旧产物。

## 配置和查看

```dotenv
MINIAGENT_TRACE_ENABLED=true
# Windows 建议明确指定 D 盘；不设置则沿用项目 data/traces。
MINIAGENT_TRACE_DIR=D:/miniAgent2.0-experiments/traces
MINIAGENT_LANGSMITH_EXPORT=false
MINIAGENT_LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=
```

本次没有改动用户 `.env`；真实验收通过进程环境变量指定 D 盘。日常需要 D 盘保存摘要时，把上述路径加到自己的 `.env` 后重启。不要设置框架自动追踪来替代这个摘要出口。

摘要示意（无原文）：

```json
{"mode":"forced","status":"completed","elapsed_ms":6203.0,"selected_count":1,"candidate_count":2,"tools":{},"security_counts":{"workflow.allowed":1,"output.allowed":1}}
```

本地 JSON 可直接打开检查；没有新增会暴露个人摘要的 HTTP 列表接口，也没有改造聊天页面。

## 使用 LangSmith

当前实现和验证不需要账号。本次没有向 LangSmith 发送真实网络请求。若要看远程看板，需要自行创建 LangSmith 账号并获取该服务的 API key（不是 DeepSeek key），按服务页面选择区域对应 HTTPS 地址。

在 `.env` 设置 `LANGSMITH_API_KEY`，显式设 `MINIAGENT_LANGSMITH_EXPORT=true`，重启终端命令后执行：

```powershell
conda activate miniAgent2.0
python -m miniagent.cli.export_trace D:/miniAgent2.0-experiments/traces/运行UUID.json
```

导出仍然是手动动作，聊天不会自动上传。固定项目为 `miniagent-sanitized`；输入只有 mode，输出只有计数和状态。重新构建白名单后再调用已安装 SDK，禁用自动批处理及运行环境附加信息，客户端使用完即关闭。失败不输出 SDK 异常正文。

**验证范围**：本地摘要及导出字段已用模拟客户端验证；尚未验证真实账号、区域、项目权限或云端展示。没有配置账号时不能声称云端已验收。当前也没有上传数据集、原文或真实模型评分结果到 LangSmith。

## 可复现实验和版本对比

在指定的原 Python 环境执行：

```powershell
& D:\.conda\envs\miniAgent2.0\python.exe -B -m miniagent.cli.evaluate run --output-dir D:/miniAgent2.0-experiments/phase5
```

每次产生新目录，不覆盖以前结果：

```text
security-<UUID>/
├── manifest.json          # Git commit、当前源码 SHA256、数据集 SHA256、Python 和依赖版本
└── security-report.json   # 原第四阶段逐条合成安全结果、指标、限制
```

源码指纹覆盖源码文件、实验实现、requirements 和默认策略。未提交修改也影响指纹，因此仅看 Git commit 不会误认为两个工作区完全相同。实验沿用固定合成策略，不读取正式知识库，也不调用生成模型。它是片段暴露/规则误报实验，不是端到端攻击成功率。

比较两个报告：

```powershell
python -m miniagent.cli.evaluate compare 旧目录/security-report.json 新目录/security-report.json --output D:/miniAgent2.0-experiments/comparison.json
```

数据集 SHA256 不同就拒绝直接比较，输出文件已存在也拒绝覆盖。比较已保护上下文暴露数、误报数和事实投毒识别数；耗时不作为自动回归门槛，硬件与缓存变化会影响计时。

GitHub Actions 执行相同离线实验，报告上传为 artifact，不包含正式资料或密钥。CI 没有执行模型计费请求，也没有 LangSmith 云端导出。

## 本次验收材料与结果

- **合成事件与假秘密**：验证摘要不包含问题、回答、原文、推理；人为添加的未知字段与工具名不导出；远程关闭时不构建客户端；失败/取消留记录；消费者收到终态即结束也能保存；写盘失败不破坏回答。
- **版本比较**：合成前后计数，验证增减值；不同数据集拒绝比较。
- **第四阶段相同 14 条合成文本**：8 条注入、5 条正常内容、1 条假事实，结果保持 7/8 拦截、正常保留 5/5、假事实未识别。第四与第五阶段报告比较的三项差值均为 0；不是安全检测能力提升的证据。
- **真实原模型链路**：两份虚构资料“冷却液九天更换”“备份十四天保留”，加未涉及的月球问题，DeepSeek + Ollama + ONNX 三轮全部通过；六条隔离消息，三份无原文运行摘要。强制问答和自动工具调用均正常。

真实联调：`D:\miniAgent2.0-experiments\phase5\live-api-0zq60u25\report.json`。脱敏摘要：同级 `traces/`。回归日志：`tests.txt`。版本比较：`phase4-vs-phase5.json`。

最终 Python 回归 **80 项全部通过，无跳过**，其中本阶段新增 6 项。`pip check` 和 Git 差异空白检查通过。此阶段没有改动前端，因此未重复浏览器验收。

没有下载依赖，没有修改全局 Python、模型服务或正式知识库。源码仍在原工作区；原回归缓存与默认日志沿用项目目录，新增真实联调及评测产物在 D 盘。原规则对改写注入和假事实的能力缺口保留，完整人工审批、多用户身份隔离和独立攻击评测仍需后续实现。
