@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建 Python 环境...
  py -3.13 -m venv .venv
  if errorlevel 1 py -m venv .venv
  if errorlevel 1 goto error
  echo 正在安装依赖，首次启动需要联网...
  .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  if errorlevel 1 goto error
)
echo 工作台地址：http://127.0.0.1:8765/
echo 保持此窗口打开。关闭窗口即可停止服务。
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
if errorlevel 1 goto error
goto end
:error
echo 启动失败，请截图错误信息或复制后发给我。
pause
:end
