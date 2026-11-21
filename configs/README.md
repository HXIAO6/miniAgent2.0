# 配置目录

`security.json` 是第四阶段启用的服务端安全策略，不含密钥，可以提交 Git。

- `allowed_sources: null`：允许本机用户导入的所有文档名，仍进行内容检查；改为 `[]` 则不允许任何文档。
- `allowed_sources: ["维护.md"]`：只允许指定文档名参与入库和检索。
- `denied_sources`：文档名黑名单，优先于白名单。
- `allowed_tools`：普通聊天的工具白名单，默认只有 `get_current_time`。可显式添加 `search_web` 或 `read_local_file`；不能添加写入工具。

配置错误会阻止启动，不会静默关闭防护。修改后重启；浏览器和模型不能覆盖该文件。文件名策略仅用于个人单机服务，不是用户身份或租户隔离。

`.env` 中的 `SECURITY_POLICY_PATH` 可指定其他策略文件；`TOOL_WORKSPACE` 指定只读文件工具的沙箱。沙箱默认位于项目根目录 `tool_workspace/`，也可指定 D 盘绝对目录。不要把密钥、正式知识库或数据库放入工具沙箱。

实验报告和策略限制见 [第四阶段说明](../docs/phase4.md)。
