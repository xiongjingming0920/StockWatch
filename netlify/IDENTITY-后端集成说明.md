# Netlify Identity 后端集成准备

此文件描述账号集成准备。2026-11-09 站点所有者确认 Identity Registration 已改为 Open；站点仍受 Netlify 团队登录保护。生产环境设置 `STOCKWATCH_AUTH_MODE=identity` 和 `STOCKWATCH_SIGNUP_ENABLED=true`，供所有者自主注册测试；后端测试期默认只允许 `super_admin` 角色访问 Agent。尚需完成邮箱验证、后台授予角色及真实登录联测，不能视为对普通用户正式开放。

## 模式与接口

- 未配置 `STOCKWATCH_AUTH_MODE` 或设置 `site_token`：保留原始服务端口令校验。
- 设置 `STOCKWATCH_AUTH_MODE=identity`：除健康检查外的 API 使用 `@netlify/identity` 的服务端 `getUser()`；无已验证身份返回 401，服务不可用时返回 503。非 GET/HEAD/OPTIONS 请求额外执行 `verifyRequestOrigin()`，缺少 Origin 或跨源返回 403。配置其他值时拒绝访问，不会悄然回退到匿名。
- `GET /api/v1/health` 返回 `auth_mode` 和 `site_token_required`。`GET /api/v1/session` 在对应模式认证成功后返回 `auth_mode` 和当前用户（口令模式中 user 为 null）。
- 身份模式下，巡检状态按经身份服务验证的用户 ID 哈希命名空间分别存储；旧共享口令模式的状态不自动迁移给任何用户。内置公开历史数据与批次 ID 仍是共享的，不等于提供了私有数据资产隔离。
- 身份模式的 `STOCKWATCH_ACCESS_MODE` 缺省为 `admin_only`：仅允许 Netlify Identity 可信 `user.roles` 中含 `super_admin` 的用户调用业务 API；未知策略会拒绝访问。未来 `registered` 仅在明确上线决策后启用，且需先完成平台公开注册设置、滥用防护和费用限制。`STOCKWATCH_SIGNUP_ENABLED` 只控制网站是否显示注册表单，不改变 Identity 的 Open/Invite only 平台策略，也不授予 Agent 权限。
- Identity 模式下，前端在服务端确认用户 ID 后使用按 ID 区分的浏览器本地存储键；旧共享记录不自动迁移。这样可减少同一浏览器正常切换账号时的混淆，但本地存储并非对同设备其他使用者的强安全边界，也不会跨设备同步。当前没有用户级配额、全局开销上限或跨设备数据库，公开邀请前应单独处理。

## 测试与部署前置

浏览器端 SDK 的固定版本构建方法（项目根目录）：先执行 `npm ci`，再执行 `npx.cmd --yes esbuild@0.25.12 frontend/vendor/identity-entry.js --bundle --format=esm --platform=browser --outfile=frontend/vendor/identity-client.js`。SDK 版本由 `package-lock.json` 固定。构建工具来自 npm，升级版本后需重新审查和测试。

`node netlify/test-identity.mjs` 使用模拟平台身份上下文、无凭据请求与跨源请求；`node netlify/test-identity-ui.mjs` 检查前端与会话接口的响应契约。这些检查不能代替在真实 Netlify 环境验证。`node netlify/test.mjs`、`node netlify/test-generic.mjs` 可验证默认口令模式未回归。

依赖 `@netlify/identity` 2.x，需要 Node.js >= 22.12，实际 Netlify build/runtime 须验证。当前先保持团队保护：所有者通过注册页面注册并验证邮箱，再由 Netlify Identity > Users 中的可信管理界面将该用户角色设置为 `super_admin`，重新登录后测试。SDK 文档表明 Netlify Identity 无法在 `netlify dev` 完整模拟；仍需真实环境验证注册、登录和密码重设。公开生产页面前应单独验证未登录 API 返回 401、非管理员 403、伪造身份不得访问、跨用户状态隔离、CSRF 拒绝以及旧站点口令不能绕过身份模式。
