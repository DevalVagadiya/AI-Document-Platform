# AI Document Intelligence Platform

A production-grade multi-tenant AI Document Intelligence SaaS built with FastAPI, ChromaDB, SentenceTransformers, and Gemini 2.5 Flash.

## Quick Start

```bash
# Activate environment
.venv\Scripts\activate

# Run dev server
uvicorn app.main:app --reload
```



celery -A app.workers.celery_app worker --loglevel=info -Q ingestion -P solo

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

npm run dev

abc@gmail.com
Abc@1234

xyz@gmail.com
Xyz@1234