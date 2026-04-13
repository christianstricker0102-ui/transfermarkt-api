import os
import json
import time

import uvicorn
from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import RedirectResponse

from app.api.api import api_router
from app.services.base import _session, _check_waf_block, COOKIE_FILE
from app.settings import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMITING_FREQUENCY],
    enabled=settings.RATE_LIMITING_ENABLE,
)
app = FastAPI(title="Transfermarkt API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
def docs_redirect():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["system"])
def health_check():
    """Prueft ob TM-Cookies gueltig sind (echter Request)."""
    cookie_path = os.path.normpath(COOKIE_FILE)

    # Cookie-Datei-Info
    cookie_age_hours = None
    cookie_count = 0
    if os.path.exists(cookie_path):
        cookie_age_hours = round((time.time() - os.path.getmtime(cookie_path)) / 3600, 1)
        try:
            with open(cookie_path) as f:
                cookie_count = len(json.load(f))
        except Exception:
            pass

    # Echter TM-Request (leichtgewichtige Seite)
    tm_ok = False
    detail = None
    try:
        resp = _session.get("https://www.transfermarkt.com/", timeout=10)
        if _check_waf_block(resp):
            detail = "WAF-Block — Cookies abgelaufen"
        else:
            tm_ok = True
    except Exception as e:
        detail = f"Request fehlgeschlagen: {e}"

    status = "ok" if tm_ok else "captcha_required"
    return {
        "status": status,
        "cookies": {"count": cookie_count, "age_hours": cookie_age_hours},
        "detail": detail,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
