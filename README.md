# StockWatch：生鲜缺货巡检工作台

这是用于学习和测试的本地原型：用 FreshRetailNet-50K 真实历史数据的固定子集，按过去七天缺货天数排序，生成巡检清单并查询个案。**它不是实时业务系统，不会下单或发送信息。**

## 快速启动（Windows）

1. 安装 Python 3.13（推荐；3.10+ 可尝试）并确保 `py` 可用。
2. 双击 `启动工作台.bat`。第一次会在项目内创建 `.venv` 并安装依赖，需要联网；请等待窗口显示服务已启动。
3. 打开 <http://127.0.0.1:8765/>，首次注册的账号会成为本机超级管理员。使用自己设置的邮箱和密码注册并登录，然后即可开始对话或使用巡检功能。
4. 测试期间允许注册其他账号，但只有超级管理员能使用业务功能。账号保存在 `backend/data/local-auth.sqlite3`，不能在其他设备或线上直接使用；当前没有密码找回功能，请妥善保管密码和本机账号数据库。
5. 关闭启动窗口可停止服务。人工操作记录保存在 `backend/data/stockwatch.sqlite3`。

仓库不包含本机账号、聊天记录或 DeepSeek 密钥。下载后首次在本机注册的账号会成为该副本的管理员，实际密钥由使用者自行在本机配置。若首次创建虚拟环境后安装依赖失败，可在项目根目录运行 `.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`，再重新启动。

macOS / Linux 可在项目根目录运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

然后打开 <http://127.0.0.1:8765/>。该路径尚未在所有系统上验证。

如端口被占用，在 PowerShell 中从项目根目录执行：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

访问 <http://127.0.0.1:8766/>。API 文档位于对应地址的 `/docs`。

## 当前能力和边界

- 样本来自 FreshRetailNet-50K 的真实公开数据，200 个匿名门店—商品组合，按训练首日 ID 选取，包含 19,400 条 2024-03-28 至 2024-07-02 记录。来源、数据版本与许可见 `backend/data/source.json`。
- 系统默认规则排序为过去 7 天缺货天数除以 7，**不是概率**。另提供基于真实子集训练的轻量逻辑回归测试模型；分数未经校准，不当作可靠概率。由于模型验证数据截至 2024-06-20，模型模式仅允许该日期及之后回放，防止未来信息泄漏。测试模型及规则的历史回放指标见 `backend/models/risk_model.json` 或 `/api/v1/model`；这些指标不代表真实业务收益。没有使用 LightGBM 或 DuckDB。
- LangGraph 用于组织调查步骤。配置 DeepSeek 后可围绕当前个案多轮对话；模型可调用受控只读工具查询个案摘要和截止回放日的缺货记录，然后生成回答。回答可能有误，应展开工具证据核对。未配置模型或调用失败时明确降级到规则回答；不执行模型生成的代码或 SQL。
- 回放使用截至 T 日的数据，未来记录仅用于回测；没有库存量、采购单、供应商交期或真实处理结果，不可推断补货量和缺货原因。
- SQLite 是本地单机状态数据库；本机巡检会保存有限的运行元信息，但并非可完整复现的持久化审计系统。
- 用户可以为个案新建、切换和删除多个对话。消息按账号保存在当前浏览器的本地存储中，清除浏览器数据或更换设备后无法恢复，也不会随账号跨设备同步；每次请求只携带最近 10 条消息。个案不可用或数据版本变化时，旧记录仍可查看，但不能继续基于旧会话提问。
- 接入本机账号前的浏览器对话记录与登录后的账号记录使用不同存储空间，旧记录不会自动迁移。
- 本机生鲜巡检助手的新回复支持“查看运行过程”：每次运行的状态、步骤和耗时保存在本地 SQLite，和浏览器里的对话文本分开；通用对话暂未接入。设计、权限和局限见 [Harness 运行记录设计](docs/Harness-运行记录设计.md)。

## 通用对话和自带数据集

无需选择巡检个案即可开始通用对话；可在通用会话中上传 UTF-8 CSV 或 TXT（每个文件不超过 200 KB；CSV 最多 5000 行、50 列），或上传 ZIP 并选择其中一个 CSV/TXT。CSV 支持数据概况、缺失情况、数值统计和分组汇总；TXT 支持文本概况、分段阅读和关键词查找。ZIP 最多 2 MB、100 个条目，声明的解压总大小不超过 4 MB；选中文件会流式解压并限制实际输出，不支持加密或嵌套 ZIP。系统使用受限工具计算，不执行模型生成的 Python 或 SQL。当前仅提供只读分析，不自动修改文件、下单或执行外部操作；Excel 文件请先另存为 UTF-8 CSV。

对话消息保存在当前浏览器，原始文件仅保存在当前页面内存，刷新后需重新选择相同文件；ZIP 仅在浏览器本地解压。发起请求时，所选文件内容发送到本站后端处理，问题、列名、文本片段、数据摘要与工具结果可能发送到 DeepSeek；不要上传不愿向服务方披露的数据。模型每次只参考最近 10 条消息。

## 可选：配置 DeepSeek 对话

复制 `backend/.env.example` 为 `backend/.env`，手动填入提供方 API 地址、模型名称和密钥后重启服务。DeepSeek 示例：地址 `https://api.deepseek.com`，模型 `deepseek-flash`；实际可用性、资费和数据政策以提供方为准。请求会把你的问题、当前会话历史和所需工具结果发送给所配置的提供方，因此只配置你信任的服务。密钥绝不提交代码或共享给他人。未配置不会阻止使用规则功能。

## Netlify 适配

`netlify/` 和 `netlify.toml` 提供可离线测试的 Node Functions 适配；它与本机 Python/LangGraph 是不同实现。口令和 DeepSeek 密钥必须放在 Netlify 服务端环境变量中，不放入网页。部署准备、访问限制和已知约束详见 `Netlify-部署说明.md`；未经真实上线验证时，不能将适配代码当作已完成部署。

## 测试

### 生鲜数据合同与离线评测

本项目提供针对 FreshRetail 生鲜巡检数据的**数据合同检查器**和一套固定金标评测。本机 Python 版会在生成巡检批次前检查合同，失败时阻断；也可在生鲜巡检区域查看检查报告。通用对话上传文件和 Netlify 适配不经过这一生鲜合同。评测默认禁用模型，使用临时数据库，不影响正常业务数据。详细说明、金标来源和限制见 [数据合同与评测说明](数据合同与评测说明.md)；架构现状和后续实施路线见 [架构差距与实施路线](docs/架构差距与实施路线.md)。

在项目根目录，先按项目启动说明准备 `.venv`，然后运行：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.data_contract --as-of 2024-07-01 --require-reference --output ..\reports\data-contract-report.json
cd ..
.\.venv\Scripts\python.exe evals\run_eval.py
```

合同的 `pass / warn / fail` 是对静态文件的检查结果，不能证明数据在 T 日已可用，也不证明线上执行了过滤。评测报告中 `unassessed` 的模型用例不算通过。更换真实数据前需审核并版本化合同和金标，不应简单改哈希让测试通过。

```powershell
cd backend
..\.venv\Scripts\python.exe -m pip install pytest
..\.venv\Scripts\python.exe -m pytest -q tests
```

`/api/v1/batches/{batch_id}/evaluation` 提供次日已知标签的简单回放统计；缺失标签不计为负样本。历史回放不证明实际干预减少缺货。

## 目录

- `backend/app/`：API、规则回放、LangGraph 调查流程。
- `backend/models/`：可复现的逻辑回归模型参数和历史对比报告；可在 `backend` 目录运行 `python -m app.train_risk` 重新训练（会覆盖模型文件，已有批次引用的数据/模型版本可能随之失效）。
- `backend/data/`：真实公开数据子集和来源；运行后生成本地 SQLite。
- `backend/tests/`：时间泄漏、缺失数据、幂等与调查流程测试。
- `frontend/`：同源工作台页面。
- `tools/prepare_freshretail.py`：数据子集重新生成脚本，需要 DuckDB；脚本会下载公开原始数据。

数据来源：[FreshRetailNet-50K](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K)；遵循其 CC BY 4.0 数据许可并保留署名。使用或再发布前请查看数据集的最新许可及说明。
