# AI Intelligence Platform

Runnable starter application: **React + ASP.NET Core 8 + Python FastAPI/LangGraph + PostgreSQL/pgvector + Redis + MinIO**.

## Requirements
- Docker Desktop with Docker Compose v2
- 4 GB+ free memory recommended
- Ports 5173, 5000, 8000, 5432, 6379, 9000 and 9001 available

## Run
Windows PowerShell:
```powershell
Copy-Item .env.example .env
docker compose up --build
```
macOS/Linux:
```bash
cp .env.example .env
docker compose up --build
```

Open: frontend http://localhost:5173 · ASP.NET Swagger http://localhost:5000/swagger · AI docs http://localhost:8000/docs · MinIO http://localhost:9001 (platform / minio_dev_password).

Default `LLM_PROVIDER=mock` lets you exercise the workflow without a key; it is **not real model inference**. For OpenAI, set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `.env`, then run `docker compose up -d --build ai-service`. Never commit `.env` or use development credentials in production.

## Operations
```bash
docker compose ps
docker compose logs -f frontend backend ai-service
docker compose down
```
Destructive reset: `docker compose down -v`.

## Included in this baseline
- Dashboard, Agent Studio, Knowledge Center, AI Playground, model configuration, cost metrics, traces, and security scan UI
- LangGraph agent pipeline with conditional routing and tool calling: Supervisor classifies the request, Security Agent blocks prompt injection before the model is called, Analysis Agent filters suspicious retrieved context
- Document ingestion from pasted text or uploaded PDF/DOCX/TXT/MD (original kept in a Docker volume; S3-compatible storage optional), paragraph-aware chunking
- Hybrid retrieval: keyword + Gemini embeddings in pgvector, fused with weighted Reciprocal Rank Fusion (falls back to keyword search when embeddings are unavailable)
- Conversations saved in PostgreSQL (list, reopen, delete) and answers streamed over Server-Sent Events
- Chat/model adapter and request/token/cost/latency logging
- Per-step traces and heuristic prompt-injection pattern detection

## Known limitations / production work
- The Tool Agent (Gemini function calling) can call four read-only tools (list/search/read documents, calculator), enabled per tool in the `agent_tools` table; tool output passes through the Security Agent. Retries, write actions, and human approval are not implemented.
- Embeddings need `LLM_PROVIDER=gemini`; document text is sent to Google's API to create vectors.
- Scanned (image-only) PDFs are rejected: there is no OCR.
- Streaming: Gemini text streams chunk by chunk; blocked replies and Tool Agent answers arrive in one piece. Conversations are shared (no login yet).
- Redis is provisioned but not yet used for caching.
- MinIO is optional (`--profile s3`, `STORAGE_BACKEND=s3`): its images were removed from Docker Hub and the quay.io tags are no longer reliably pullable, so uploads default to a local volume.
- Prompt-injection scanning is a small pattern list, not a security guarantee.
- Cost uses illustrative token rates, not provider billing.
- Authentication, RBAC, tenant isolation, rate limits, TLS, secrets management, backups, malware scanning, and production observability are not implemented.

Architecture: `Browser → Nginx/React → ASP.NET Core API → FastAPI/LangGraph → PostgreSQL`. Browser requests go through the ASP.NET `/api/platform/*` proxy.