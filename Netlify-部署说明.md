# Netlify 测试部署说明

Netlify 的站点前端和服务端函数通过 CLI 从本地部署，不需要建立或推送 GitHub 仓库。公开页面使用 `frontend/`，API 由 `netlify/functions/api.mjs` 提供。Python 后端在本机继续可用；**线上为独立 Node 适配实现，不运行 Python 和 LangGraph**。两种实现是独立代码路径，需要分别测试，不能把线上展示说成 LangGraph 已在线运行。

数据为 FreshRetailNet-50K 的公开真实历史数据子集；`backend/data/source.json` 包含来源及许可信息。Netlify Functions 通过 included_files 随包读取样本和离线模型。排序及评测是历史回放，没有实时库存，也不能证明真实业务收益。使用 `@netlify/blobs` 保存工单状态：这是站点级存储，跨实例共享，强一致读取，单 key 并发写入为最后一次写入生效；它不是完整的工单审计数据库。是否成功随项目启用需要真实部署验证，存储失败时页面应报告错误。

## 访问控制与密钥

上线前须为 Netlify 项目的 **Functions 运行时**配置：

- `STOCKWATCH_SITE_TOKEN`：至少 32 字符的高随机性访问口令。前端只在当前浏览器会话输入并保存在 sessionStorage，用 `X-Stockwatch-Token` 请求 API。未配置、过短或口令不匹配时 API 不提供数据和模型调用。
- `STOCKWATCH_LLM_API_KEY`：DeepSeek 密钥，仅供服务端函数读取。不要将密钥放在 HTML、前端 JavaScript、`netlify.toml`、源码仓库或日志中。

系统会将用户的问题、当前会话历史和所需工具结果发送给 DeepSeek，用于多轮对话；数据查询和统计由受控工具执行。模型回答可能有误，需要结合工具证据核对。未配置模型密钥或调用失败时明确降级。外部模型调用可能发生费用：长随机口令及每 IP 限流只减少风险，并非完整身份系统或全局费用上限，建议限制密钥预算、不要把口令分享给他人，并将站点设为私有（如账号支持）。真实发布后需核验限流部署日志、401 和 503 路径，以及模型和状态保存行为。

## 本地验证

```powershell
npm install
node netlify/test.mjs
```

测试使用虚构口令和内存存储，不代表 Netlify Blobs 已真实连接或生产安全已验证。部署时请在自己的 Netlify 账号中设置以上两个运行时变量后，再通过 `npx netlify-cli deploy` 进行预览；不要把 `backend/.env`、本地数据库和 `node_modules` 当作静态页面上传。账号、计划配额和部署状态以 Netlify 当前界面为准。
