# AI Document Platform: Architecture Deep Dive

Welcome to the codebase! Since you have 1.5 years of Python experience, you likely already know the basics of web frameworks and APIs. This document bridges the gap between basic Python scripts and **enterprise-grade, production-ready SaaS architecture**. 

Here is exactly how this multi-tenant AI RAG (Retrieval-Augmented Generation) pipeline works from the inside out.

---

## 1. High-Level Stack
*   **Web Framework**: FastAPI (blazing fast, async by default, heavily relies on Pydantic for validation).
*   **Database (Relational)**: PostgreSQL via **SQLAlchemy 2.0** (using `asyncpg` for non-blocking database queries) and Alembic for migrations.
*   **Database (Vector)**: ChromaDB (stores our AI embeddings for semantic search).
*   **AI/ML**: `sentence-transformers` (local embeddings to save money) and Gemini 2.5 Flash (the brain/LLM).
*   **Security**: JWT (JSON Web Tokens) with RS256 asymmetric encryption, Argon2/Bcrypt for password hashing.

---

## 2. Core Concept: Multi-Tenancy
This is a **B2B SaaS** application. This means multiple companies (Tenants) use the same database. 
*   **Rule #1**: Users belong to a `Tenant`.
*   **Rule #2**: Documents belong to a `Tenant`.
*   **Rule #3**: Every database query and vector search **must** filter by `tenant_id`. If user A (from Company A) queries the database, the code explicitly ensures they can never see Company B's documents.

---

## 3. The Three Main Data Flows

### A. The Auth Flow
1.  **Registration**: A user signs up (`POST /api/v1/auth/register`). We hash their password, create a `Tenant`, create a `User`, and save them to PostgreSQL.
2.  **Login**: They hit `POST /api/v1/auth/login`. We verify the hash and return an **Access Token** (short-lived JWT) and a **Refresh Token** (long-lived JWT stored in a secure HttpOnly Cookie).
3.  **Dependency Injection**: Every protected API endpoint uses `Depends(get_current_user)`. This FastAPI magic intercepts the request, reads the `Authorization: Bearer <token>` header, decodes it, fetches the user, and passes the `current_user` object into your API route.

### B. The Document Ingestion Flow (How PDFs become AI memory)
When a user uploads a PDF, it goes through a heavy pipeline:
1.  **Upload (`app/api/documents.py`)**: The router receives the file. We validate the size (max 50MB) and MIME type.
2.  **Storage (`app/services/storage_service.py`)**: We stream the file to the local disk in 1MB chunks (preventing RAM crashes). We calculate a `SHA-256` hash to prevent duplicate uploads.
3.  **Database (`app/services/document_service.py`)**: We create a `Document` record in Postgres marked as `pending`.
4.  **Background Worker (`app/workers/ingestion_tasks.py`)**: We spin up a background thread to process the file without freezing the API:
    *   **Parse**: Extract raw text (`pdfplumber` / `python-docx`).
    *   **Chunk**: Split the massive text into 512-token chunks using `tiktoken`. We overlap chunks by 64 tokens so sentences aren't cut in half.
    *   **Embed**: Convert the text chunks into arrays of numbers (vectors) using our local `SentenceTransformer` model.
    *   **Vector DB**: Store the vectors + text inside ChromaDB (`app/services/vector_service.py`).
    *   **Finish**: Mark the document as `ready` in Postgres.

### C. The RAG Streaming Flow (How the AI answers questions)
When a user asks a question (`POST /api/v1/queries`):
1.  **Embed Question**: Convert their string question into a vector using the same `SentenceTransformer`.
2.  **Vector Search**: Ask ChromaDB: *"Give me the top 5 chunks closest to this question's vector, but ONLY for this `tenant_id`."*
3.  **History**: Fetch the last 3 questions the user asked from Postgres (`QueryLog`) so the AI remembers the conversation.
4.  **Prompt Construction**: Mash the context chunks, the history, and the new question into a massive string prompt.
5.  **LLM Stream (`app/services/rag_service.py`)**: Send the prompt to Google Gemini. As Gemini types out the answer token-by-token, we yield those tokens immediately back to the frontend using **Server-Sent Events (SSE)**.
6.  **Analytics**: Once done, log the latency and token usage to `QueryLog` for billing and debugging.

---

## 4. Folder Structure (What every file does)

We use a **Layered Architecture** (Controllers -> Services -> Data). This is crucial for keeping code clean as the app grows.

### 🟢 `app/api/` (The Controllers/Routers)
*Your entry points. These files only handle HTTP requests, headers, and returning JSON. They contain NO heavy business logic.*
*   `router.py`: Aggregates all the v1 routes together.
*   `v1/auth.py`: Login, Register, Refresh endpoints.
*   `v1/documents.py`: Uploading, listing, and deleting files.
*   `v1/queries.py`: The Q&A chat endpoints.

### 🔵 `app/services/` (The Brains/Business Logic)
*This is where the actual code lives. Routers call these files. Services talk to the database.*
*   `auth_service.py`: Password hashing, JWT generation, user validation.
*   `document_service.py`: Checking for duplicate files, saving file metadata to Postgres.
*   `embedding_service.py`: Loads the ML model into memory and converts text to vectors.
*   `vector_service.py`: The wrapper around ChromaDB for saving and searching vectors.
*   `rag_service.py`: The maestro that builds prompts, talks to Gemini, and manages the SSE stream.

### 🟡 `app/models/` (The Database Tables)
*SQLAlchemy ORM (Object-Relational Mapper) classes. These represent our Postgres tables.*
*   `base.py`: The foundation class that auto-adds `id`, `created_at`, and `updated_at` to every table.
*   `tenant.py` & `user.py`: The core auth tables.
*   `document.py` & `chunk.py`: Stores metadata about uploaded files and their textual chunks.
*   `query_log.py`: The analytics table tracking every AI question asked.

### 🟠 `app/schemas/` (The Bouncers/Pydantic Models)
*Pydantic classes strictly define what JSON data is allowed IN (Requests) and OUT (Responses) of the APIs.*
*   `common.py`: Base schemas for standardizing things like pagination.
*   `auth.py`: Defines that a login request MUST have an `email` and `password`.
*   `document.py`: Defines what the JSON response for a document looks like.

### 🟣 `app/core/` (The Engine Room)
*   `config.py`: Reads the `.env` file. If a vital variable is missing, it safely crashes the app at startup.
*   `database.py`: Manages the Postgres connection pool.
*   `dependencies.py`: Holds `get_db` (which yields a fresh database session per HTTP request) and `get_current_user` (verifies JWTs).
*   `security.py` & `exceptions.py`: Cryptography helpers and custom error classes.

### 🔴 `tests/` (The Safety Net)
*   `conftest.py`: The most important test file. It automatically creates an in-memory SQLite database before every test so we can run tests without messing up our real data.
*   `integration/`: Tests the full flow (simulating real HTTP requests).
*   `unit/`: Tests isolated pieces of logic (like checking if a password hashes correctly).

---

## 5. Pro-Tips for a 1.5yr Developer

1.  **Dependency Injection**: Notice how almost every API route takes `db: AsyncSession = Depends(get_db)`. This is FastAPI's superpower. It means "Before this route runs, execute `get_db`, give me the database connection, and when the route finishes, close the connection automatically."
2.  **Async/Await**: Because Python is single-threaded, if we did a standard `time.sleep()` or a heavy file upload, the entire server would freeze for everyone else. By using `async def` and `await`, we tell Python: *"While we wait for the database/network to respond, go serve another user's request."*
3.  **`anyio.to_thread`**: In `rag_service.py` and `ingestion_tasks.py`, you'll see `anyio.to_thread.run_sync()`. When we run heavy CPU tasks (like parsing a 50-page PDF or running a Machine Learning model), we push that work onto a separate background thread so the async loop doesn't choke.
4.  **Separation of Concerns**: Notice how the `api` routes don't write SQL queries? Notice how the `models` don't return HTTP 404s? Keeping these separated means you can swap out FastAPI for Django tomorrow, or Postgres for MySQL, without rewriting the whole app.
