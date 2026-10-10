# 贡献指南

欢迎提交问题和小范围 Pull Request。请先阅读 [功能状态](docs/STATUS.md)。

## 开发验证

Windows、Python 3.12 x64：

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m unittest discover -v
```

所有自动测试只使用模拟适配器，不能发送真实微信消息。报告兼容性时写明具体微信版本、
Windows 版本、Python 版本、操作步骤及真实观察结果。不要上传聊天正文、账号标识、
联系人名单、二维码、数据库或登录凭据。

## 每次变更

- 为改变的行为提供适当验证。
- 更新 CHANGELOG.md；功能或证据变化时同时更新 README.md 和 docs/STATUS.md。
- 区分“实现”“模拟测试”“真实微信验证”，不要只用一个“支持”概括。
- 公开仓库提交示例配置，运行配置始终留在本地。
- MIT 仅覆盖本仓库自有源码，新增依赖需记录来源及自己的许可证。

仓库所有者授权的完成更新应提交并推送 GitHub，遵循 AGENTS.md；外部贡献者通过 PR 提交。
