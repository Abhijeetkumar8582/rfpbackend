"""API v1 — aggregate all routers."""
from fastapi import APIRouter

from app.api.v1 import auth, users, projects, documents, ingestion, search, audit, activity, api_keys, rfp_questions, rephrase

api_router = APIRouter()

api_router.include_router(auth.router, prefix="")
api_router.include_router(users.router, prefix="")
api_router.include_router(projects.router, prefix="")
api_router.include_router(documents.router, prefix="")
api_router.include_router(ingestion.router, prefix="")
api_router.include_router(search.router, prefix="")
api_router.include_router(audit.router, prefix="")
api_router.include_router(activity.router, prefix="")
api_router.include_router(api_keys.router, prefix="")
api_router.include_router(rfp_questions.router, prefix="")
api_router.include_router(rephrase.router, prefix="")
