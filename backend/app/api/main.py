"""FastAPI application.

    uvicorn app.api.main:app --reload

Health and provider status are deliberately unauthenticated and honest:
an operator needs to be able to see that GST is unconfigured without
logging in, because "no provider" is a fact about the platform, not a
secret about a vendor.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth_routes import router as auth_router
from app.api.client_routes import router as client_router
from app.api.routes import router
from app.config import get_settings
from app.providers.base import NotConfigured, PaidCallRefused, ProviderError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="VBC — Vendor Intelligence Platform",
    version="1.0.0",
    description=(
        "Vendor onboarding due diligence. The system automates the data "
        "layer; a named analyst retains the decision layer. It gathers, "
        "scores, drafts and flags — it never issues a binding approve or "
        "reject."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(client_router, prefix="/api")
app.include_router(router, prefix="/api")


@app.exception_handler(NotConfigured)
def handle_not_configured(request: Request, exc: NotConfigured):
    # 501, not 500: nothing is broken. The capability does not exist yet.
    return JSONResponse(status_code=501, content={"detail": str(exc)})


@app.exception_handler(PaidCallRefused)
def handle_paid_refused(request: Request, exc: PaidCallRefused):
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(ProviderError)
def handle_provider_error(request: Request, exc: ProviderError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "providers": {
            "filesure": (
                "sandbox" if settings.filesure_is_sandbox
                else "live" if settings.filesure_configured
                else "not_configured"
            ),
            "whoisxml": "live" if settings.whoisxml_configured else "not_configured",
            "archive": "live",
        },
        "paidCallsEnabled": settings.allow_paid_calls,
    }
