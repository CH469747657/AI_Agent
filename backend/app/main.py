"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routers import invoices, projects, reports, wecom, reimbursements, employees
from app.routers import portal_auth, portal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    await init_db()
    # 预加载OCR模型
    from app.services.ocr_service import get_ocr_service
    get_ocr_service()  # 触发懒加载
    yield


app = FastAPI(
    title="发票报销智能助手",
    description="基于OCR+LLM双源验证的报销预审系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(invoices.router, prefix="/api/invoices", tags=["发票管理"])
app.include_router(projects.router, prefix="/api/projects", tags=["项目管理"])
app.include_router(reports.router, prefix="/api/reports", tags=["报表生成"])
app.include_router(wecom.router, prefix="/api/wecom", tags=["企业微信"])
app.include_router(reimbursements.router, prefix="/api/reimbursements", tags=["报销单管理"])
app.include_router(employees.router, prefix="/api/employees", tags=["员工管理"])

# 员工端路由（portal）
app.include_router(portal_auth.router, prefix="/api/portal/auth", tags=["员工端-认证"])
app.include_router(portal.router, prefix="/api/portal", tags=["员工端-业务"])


@app.get("/")
async def root():
    return {"name": "发票报销智能助手", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}
