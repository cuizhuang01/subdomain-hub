"""FastAPI 应用入口。"""
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import settings_store
from .db import get_conn, init_db
from .routers import admin, apiv1, auth, dns, domains, stats
from .routers.gateway import install_gateway

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "app", "static")

app = FastAPI(
    title="云子域 · 二级域名分发系统",
    description="二级域名申请、审核、跳转分发、DNS 解析托管、访问统计与开放 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

install_gateway(app)

app.include_router(auth.router)
app.include_router(domains.router)
app.include_router(dns.router)
app.include_router(stats.router)
app.include_router(admin.router)
app.include_router(apiv1.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    with get_conn() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return JSONResponse({}, status_code=204)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    msg = first.get("msg", "参数校验失败")
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse({"detail": f"{loc}: {msg}" if loc else msg}, status_code=422)
