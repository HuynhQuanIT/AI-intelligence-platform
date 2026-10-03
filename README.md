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
- Sequential LangGraph agent pipeline
- Document ingestion, chunking, and lexical retrieval
- Chat/model adapter and request/token/cost/latency logging
- Per-step traces and heuristic prompt-injection pattern detection

## Known limitations / production work
- Agent execution is sequential; conditional delegation, retries, tool permissions, and human approval are not implemented.
- Retrieval is lexical. pgvector is installed, but embeddings are not generated or searched.
- Redis and MinIO are provisioned but not yet connected to application caching or file-upload flows.
- Prompt-injection scanning is a small pattern list, not a security guarantee.
- Cost uses illustrative token rates, not provider billing.
- Authentication, RBAC, tenant isolation, rate limits, TLS, secrets management, backups, malware scanning, and production observability are not implemented.

Architecture: `Browser → Nginx/React → ASP.NET Core API → FastAPI/LangGraph → PostgreSQL`. Browser requests go through the ASP.NET `/api/platform/*` proxy.
