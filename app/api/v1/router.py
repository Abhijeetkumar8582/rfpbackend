"""API v1 — aggregate all routers."""
from fastapi import APIRouter

from app.api.v1 import (
    access_intelligence,
    activity,
    analytics,
    api_credentials,
    auth,
    documents,
    endpoint_logs,
    projects,
    rephrase,
    search,
    users,
    rfp_questions,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="")
api_router.include_router(users.router, prefix="")
api_router.include_router(projects.router, prefix="")
api_router.include_router(documents.router, prefix="")
api_router.include_router(search.router, prefix="")
api_router.include_router(analytics.router, prefix="")
api_router.include_router(activity.router, prefix="")
api_router.include_router(rephrase.router, prefix="")
api_router.include_router(endpoint_logs.router, prefix="")
api_router.include_router(access_intelligence.router, prefix="")
api_router.include_router(api_credentials.router, prefix="")
api_router.include_router(rfp_questions.router, prefix="")