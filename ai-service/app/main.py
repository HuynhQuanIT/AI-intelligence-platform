"""Điểm vào của ai-service: tạo ứng dụng FastAPI và gắn các router."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat, conversations as conversations_api, documents, health, monitoring, security
from .core.db import init_pool
from .services import conversations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi tạo tài nguyên database khi ứng dụng khởi động."""
    init_pool()
    try:
        conversations.ensure_schema()
    except Exception:
        logger.exception("Could not create conversation tables")
    yield


app = FastAPI(
    title="AI Intelligence Platform - AI Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, chat, conversations_api, documents, monitoring, security):
    app.include_router(module.router)
