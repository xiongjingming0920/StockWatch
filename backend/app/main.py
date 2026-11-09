from __future__ import annotations

from datetime import date
from typing import Literal
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Optional local configuration; secrets never need to be placed in source code.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
from . import services, local_auth

app = FastAPI(title="StockWatch API", version="0.1.0")
app.include_router(local_auth.router)

@app.middleware("http")
async def local_auth_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        if not local_auth.loopback_request(request):
            return JSONResponse(status_code=403, content={"detail": "本机模式只允许本机访问。"})
        if request.method not in ("GET", "HEAD", "OPTIONS") and not local_auth.valid_origin(request):
            return JSONResponse(status_code=403, content={"detail": "请求来源无效。"})
        if request.headers.get("origin") and not local_auth.valid_origin(request):
            return JSONResponse(status_code=403, content={"detail": "请求来源无效。"})
        public = {"/api/v1/health", "/api/v1/auth/register", "/api/v1/auth/login"}
        if path not in public:
            user = local_auth.current_user(request)
            if not user:
                return JSONResponse(status_code=401, content={"detail": "请先登录。"})
            if path not in {"/api/v1/session", "/api/v1/auth/logout"} and "super_admin" not in user["roles"]:
                return JSONResponse(status_code=403, content={"detail": "当前仅管理员可使用工作台。"})
            request.state.user = user
    return await call_next(request)

@app.get("/api/v1/session")
def session(request: Request):
    return {"user": request.state.user}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Avoid echoing malformed Unicode or user-provided file contents.
    return JSONResponse(status_code=422, content={"detail": "请求格式或内容无效。"})



class BatchRequest(BaseModel):
    as_of_date: date
    k: int = Field(default=50, ge=1, le=1000)
    method: Literal["rule", "model"] = "rule"


class ReviewRequest(BaseModel):
    action: str
    note: str = Field(default="", max_length=2000)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "auth_mode": "local", "registration_open": True}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, request: Request):
    from . import run_store
    result = run_store.get_run(run_id, request.state.user["id"])
    if result is None:
        raise HTTPException(404, "运行记录不存在。")
    return result


@app.get("/api/v1/dataset")
def dataset():
    return services.dataset_info()


@app.get("/api/v1/data-quality")
def data_quality(as_of: str | None = None):
    from .data_contract import validate
    return validate(services.data_path(), as_of=as_of)


@app.get("/api/v1/dates")
def dates():
    try:
        return {"dates": services.available_dates()}
    except (ValueError, OSError) as e:
        raise HTTPException(503, str(e)) from e


@app.get("/api/v1/model")
def model_info():
    from . import risk_model
    try:
        meta = risk_model.model_metadata()
        data = services.dataset_info()
        if not data["available"] or meta["dataset_sha"] != data["dataset_sha"]:
            return {"available": False, "error": "模型与当前数据版本不一致"}
        return {"available": True, **meta}
    except (OSError, ValueError, KeyError) as e:
        return {"available": False, "error": str(e)}


@app.post("/api/v1/batches")
def create_batch(request: BatchRequest):
    try:
        return services.build_batch(request.as_of_date.isoformat(), request.k, request.method)
    except services.DataContractError as e:
        return JSONResponse(status_code=422, content={"detail": str(e), "data_quality": e.report})
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/v1/batches/{batch_id}")
def batch(batch_id: str):
    item = services.get_batch(batch_id)
    if not item:
        raise HTTPException(404, "批次不存在")
    return {**item, "status": "completed"}


@app.get("/api/v1/batches/{batch_id}/cases")
def cases(batch_id: str):
    result = services.get_cases(batch_id)
    if result is None:
        raise HTTPException(404, "批次不存在")
    return result


@app.get("/api/v1/batches/{batch_id}/evaluation")
def evaluation(batch_id: str):
    try:
        result = services.evaluate_batch(batch_id)
    except (OSError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    if result is None:
        raise HTTPException(404, "批次不存在")
    return result


@app.get("/api/v1/cases/{case_id}")
def case_detail(case_id: str):
    item = services.get_case(case_id)
    if item is None:
        raise HTTPException(404, "工单不存在")
    try:
        return {"case": item, "history": services.get_history(case_id, 7)}
    except (OSError, ValueError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/v1/cases/{case_id}/reviews")
def review(case_id: str, request: ReviewRequest):
    try:
        item = services.review_case(case_id, request.action, request.note)
        if item is None:
            raise HTTPException(404, "工单不存在")
        return item
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


try:
    from .agent import router as agent_router
    app.include_router(agent_router, prefix="/api/v1")
except ImportError as exc:
    if exc.name != "app.agent":
        raise

from .generic_chat import router as generic_chat_router
app.include_router(generic_chat_router, prefix="/api/v1")

# Serve the test UI from the same origin so it talks to the local API.
frontend = Path(__file__).resolve().parents[2] / "frontend"
if frontend.is_dir():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
