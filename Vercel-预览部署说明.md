# Vercel 预览部署说明

此配置用于个人测试，尚未在实际 Vercel 账号上验证部署。Vercel 支持从本地通过 CLI 直接部署 FastAPI，不需要上传 GitHub；代码和公开样本仍会上传到 Vercel 用于构建运行。

**重要限制：当前本地后端使用 SQLite。Vercel Function 只有实例内临时可写空间，不保证跨请求分配到同一实例；批次、工单和处理状态可能随时丢失，甚至刚生成的工单在下一请求不可见。** 页面上有临时预览提示。需要可靠的线上使用，应先将 SQLite 迁移到外部持久数据库，并实现访问控制；本适配并不实现这一能力。本地运行没有这一限制。

模型密钥不得写入代码或提交；可在 Vercel 项目环境变量中配置 `STOCKWATCH_LLM_BASE_URL`、`STOCKWATCH_LLM_MODEL`、`STOCKWATCH_LLM_API_KEY`。未配置时为规则路由，不会调用大模型。

登录现有 Vercel 账号后，在此目录运行：

```powershell
npx vercel login
npx vercel deploy
```

按平台交互选择个人项目和免费额度；默认先创建预览部署。确认实际使用条款、权限、访问限制和费用后再考虑生产发布。不要使用 `--public` 参数；勿上传 `.env`、本地 SQLite 或虚拟环境（`.vercelignore` 已列出）。发布后的访问范围应在 Vercel 项目中检查；预览网址不等于已开启访问控制。

官方参考：[FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi)、[Vercel Functions](https://vercel.com/docs/functions/runtimes)、[Vercel CLI](https://vercel.com/docs/cli/deploy)。
