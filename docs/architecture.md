# 当前目录与依赖边界

本文记录当前包结构与职责边界；第三阶段的工作流详见 [阶段说明](phase3.md)。
核心实现位于 `src/miniagent/`；根目录 `.env`、`knowledge/`、`models/` 和 `data/` 的含义及路径保持不变。

```text
miniAgent2.0/
├── pyproject.toml                 # 包元数据、资源和启动入口
├── requirements.txt               # 依赖唯一维护清单，由 pyproject 引用
├── configs/                       # 预留安全与实验配置，README 说明用途
├── migrations/                    # 预留版本化数据库迁移，本次不执行迁移
├── src/
│   ├── miniagent/
│   │   ├── __main__.py            # python -m miniagent
│   │   ├── bootstrap.py           # 依赖装配与后端选择
│   │   ├── config.py              # 项目路径、配置、日志
│   │   ├── contracts.py           # 请求与事件契约
│   │   ├── application/
│   │   │   ├── chat.py            # 聊天流程、检索注入、拒答和引用校验
│   │   │   └── documents.py       # 导入、查询、确认删除用例
│   │   ├── knowledge/
│   │   │   ├── rag.py             # 混合检索和原有索引/回收站逻辑
│   │   │   ├── ingest.py          # 解析、分块、增量入库
│   │   │   ├── rerank.py          # 原 ONNX 推理
│   │   │   └── citations.py       # 引用原始数据序列化
│   │   ├── memory/
│   │   │   ├── memory_store.py    # 原 SQLite 存储
│   │   │   └── context.py         # 按配置路径获取存储实例
│   │   ├── adapters/
│   │   │   ├── llm.py             # LangChain 实现
│   │   │   └── legacy.py          # 延迟构造旧 SDK 后端
│   │   ├── tools/
│   │   │   └── implementations.py # 时间、搜索、文件工具共用函数
│   │   ├── ui/
│   │   │   ├── app.py             # 创建页面与启动
│   │   │   ├── handlers.py        # Gradio 回调与返回格式适配
│   │   │   ├── renderers.py       # HTML、引用展开、候选表
│   │   │   └── assets/styles.css  # 页面样式
│   │   ├── cli/
│   │   │   ├── doctor.py          # 启动自检
│   │   │   └── setup_reranker.py  # 模型下载与校验
│   │   ├── prompts/               # 原回答与摘要 Prompt
│   │   ├── workflows/             # 已实现模式路由与单轮状态
│   │   ├── security/              # 预留后续安全机制
│   │   └── observability/         # 预留追踪和审计
├── examples/local_model.py        # 与正式应用分开的本地调用示例
├── tests/                         # 原测试及新增架构边界测试
├── evaluations/                   # 实验基线与合成样例
└── docs/                          # 架构、阶段记录和测试资料
```

## 调用方向

```text
启动命令 → ui.app → ui.handlers → application.chat / documents
                                      ↓
                         bootstrap 注入模型、工具、知识库
                                      ↓
                         knowledge / adapters / memory
```

顶层旧兼容脚本已移除，`src/` 中的正式源码统一位于 `miniagent/`。
页面通过 `create_app()` 或 `launch()` 创建；测试使用回调模块的延迟页面接口。
聊天历史在页面加载或用户操作时读取，而不是导入模块时打开数据库。
界面层处理 Gradio 控件，应用层返回普通数据，展示层只负责渲染。

原 Chroma/BM25/ONNX 算法没有重写。`rag.py` 仍有原有索引和文档回收实现，后续有真实需求时再抽存储接口，避免本次引入第二套存储实现。
引用数据直接使用 `knowledge.citations`，界面展示直接使用 `ui.renderers`；检索模块不再反向导入界面。
security 与 observability 仍为预留目录，不表示已经实现权限、审批、注入检测或 LangSmith 审计。

## 安装与启动

所有安装均使用用户指定的 `miniAgent2.0` 环境；本次没有下载新依赖，只将当前项目注册为可编辑包：

```powershell
conda activate miniAgent2.0
python -m pip install --no-deps --no-build-isolation -e .
python -m miniagent
```

旧 `python src/knowledge_assistant.py` 命令已移除。命令行自检、导入和模型准备：

```powershell
python -m miniagent.cli.doctor
python -m miniagent.knowledge.ingest "资料路径.md"
python -m miniagent.cli.setup_reranker
```

可编辑安装只在指定环境登记源码位置，不移动源码、个人资料或数据库，不修改全局解释器。
当前配置仍以源码项目根目录为基准，主要面向源码运行和可编辑安装；不承诺安装 wheel 后自动携带个人数据。

## 验收资料和范围

- 完整回归使用原六份虚构文档、七天更新为九天的版本样例、固定时钟、合成注入和正常教学内容。
- 包边界测试检查单一包布局、原数据根目录及导入时不创建界面/聊天库。
- 网页回归使用隔离的“冷却液每九天更换”手册，验证回答、引用、候选表、无依据拒答和消息持久化。
- 文档管理回归只用隔离的“删除测试.md”，验证确认、回收站和列表刷新。
- 真实模型网页检查继续使用原 DeepSeek 服务、Ollama BGE-M3 与 ONNX；不使用用户正式资料。

测试日志保存在 `D:\miniAgent2.0-experiments\phase2/layout-*.txt`；原脚本的临时库沿用项目 `.cache/`。

本次结果：52 项完整测试全部通过；聊天及文档管理网页接口通过；真实 DeepSeek + Ollama + ONNX 网页问答通过。
对比迁移前后的基线，30 条检索排名、四种聊天结果和八条持久化消息一致；实现文件路径与导入发生变化，因此不要求源码哈希相同。
`pip check` 和 Python 语法检查通过。未下载新的第三方依赖，项目可编辑注册仅写入用户指定的 `miniAgent2.0` 环境。

## 遗留文件清理

已移除 `src/` 顶层的十二个兼容转发模块，测试和评估脚本统一使用 `miniagent.*`。
原 `src/local.py` 移至 `examples/local_model.py`，独立示例保留，正式启动统一使用 `python -m miniagent`。
检索模块中反向转发到界面的函数也已移除，引用序列化与 HTML 展示各自保持单一实现。
`src/prompts/` 已为空；实际模板位于 `src/miniagent/prompts/`。删除本机空目录的操作被自动审批策略拒绝，空壳暂留且不会进入 Git。
顶层 `src/__pycache__/` 是已有的忽略缓存，不属于发布源码，本次保留。预留的安全、工作流等包按规划保留。

清理后使用原六份合成资料、固定时钟和注入样例完成 52 项回归，全部通过；固定回答聊天接口和隔离文档管理接口也通过。
本次未额外调用真实 DeepSeek 生成请求，未下载依赖、修改正式知识库或历史数据。
日志与基线位于 `D:\miniAgent2.0-experiments\phase2/cleanup-tests.txt` 和 `cleanup-baseline/`。
