"""Vercel entry point. This is an ephemeral, single-instance preview only.

The local entry point remains backend/app/main.py. Vercel's filesystem is not
persistent; real deployments need an external database and access controls.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
if os.environ.get("VERCEL"):
    os.environ["STOCKWATCH_DB"] = str(Path(tempfile.gettempdir()) / "stockwatch-vercel-demo.sqlite3")

from app.main import app  # noqa: E402

if os.environ.get("VERCEL"):
    from fastapi.responses import HTMLResponse
    from fastapi.routing import APIRoute

    def preview_index():
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        notice = ("<div role='status' style='background:#fff2d5;color:#6f4100;"
                  "padding:12px 16px;text-align:center;font:14px sans-serif'>"
                  "线上临时预览：工单与状态仅存当前运行实例，可能随请求分配或重启丢失；"
                  "完整可靠测试请使用本地版。</div>")
        return HTMLResponse(html.replace("<body>", "<body>" + notice, 1),
                            headers={"Cache-Control": "no-store"})

    # A route before the existing StaticFiles mount takes precedence on '/'.
    app.router.routes.insert(0, APIRoute("/", preview_index, methods=["GET"]))
