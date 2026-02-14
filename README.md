# RFP Backend

FastAPI backend for RFP document management, search, ingestion, and audit. API stubs are in place; add business logic and auth as needed.

## Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, lifespan
│   ├── config.py            # Settings from env
│   ├── database.py          # SQLAlchemy engine, session, get_db
│   ├── models/              # SQLAlchemy ORM (users, projects, documents, etc.)
│   ├── schemas/             # Pydantic request/response
│   └── api/
│       ├── deps.py          # DbSession dependency
│       └── v1/
│           ├── router.py    # Aggregates all v1 routers
│           ├── auth.py      # Register, login, refresh, logout
│           ├── users.py     # Users CRUD
│           ├── projects.py  # Projects + members
│           ├── documents.py # Upload, list, get, download, delete
│           ├── ingestion.py # Ingestion jobs
│           ├── search.py    # Search + query log
│           ├── audit.py     # Audit logs
│           ├── activity.py  # Activity logs
│           └── api_keys.py  # API keys
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
# Edit .env (DATABASE_URL, SECRET_KEY, CORS_ORIGINS)
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API base: `http://localhost:8000/api/v1`
- Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## Database

- **MySQL (RDS):** Set `DATABASE_URL=mysql+pymysql://user:pass@host:3306/RFP` in `.env`. Install driver: `pip install PyMySQL`.
- **SQLite (local):** Default `sqlite:///./rfp.db`. Tables are created on startup via `Base.metadata.create_all()`.

Use Alembic for production migrations when the schema changes.

## Document upload (embed → categorize → S3)

Upload flow:

1. **Upload file** → `POST /api/v1/documents` with `project_id`, `uploaded_by`, and `file`.
2. **Extract text** from PDF/XLSX (or use filename) for embedding and categorization.
3. **Embed** with OpenAI and store vector in `documents.embedding_json` (for cluster view / similarity).
4. **GPT** assigns one category (Finance, Security, Architecture, Compliance, Integrations) and updates `documents.cluster`.
5. **S3** upload to key `{project_id}/{cluster}/{filename}` so the file repo shows the file in the correct folder.

Env: set `OPENAI_API_KEY`, `S3_BUCKET`, and optionally `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` in `.env`.  
New columns: run `python -m migrations.add_document_cluster_embedding` once to add `cluster` and `embedding_json` to `documents`.

## Next steps

- Wire auth (get_current_user) to document upload so `uploaded_by` comes from JWT
- Implement download (stream from S3) and soft-delete
- Add ingestion worker and vector search
