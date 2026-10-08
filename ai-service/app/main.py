"""Điểm vào của ai-service: tạo ứng dụng FastAPI và gắn các router."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth as auth_api, chat, conversations as conversations_api, documents, health, monitoring, security
from .core import settings
from .core.db import init_pool
from .services import auth, conversations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Kiểm tra cấu hình và khởi tạo database khi ứng dụng khởi động."""
    settings.validate()  # từ chối chạy nếu JWT_SECRET thiếu/quá ngắn/là giá trị mẫu
    init_pool()
    conversations.ensure_schema()
    auth.ensure_schema()
    auth.bootstrap_admin()
    yield


app = FastAPI(
    title="AI Intelligence Platform - AI Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

for module in (health, auth_api, chat, conversations_api, documents, monitoring, security):
    app.include_router(module.router)
