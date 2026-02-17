"""flyRoom Super Admin Console — FastAPI application."""

from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from admin_app.auth import create_session_token, verify_password
from admin_app.config import settings
from admin_app.dependencies import get_db, require_admin
from admin_app.services import dashboard, export, tenants, users

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="flyRoom Admin", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username != settings.admin_username or not verify_password(
        password, settings.admin_password_hash
    ):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid credentials"}, status_code=401
        )
    token = create_session_token(username)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("admin_session", token, httponly=True, samesite="lax", max_age=86400)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


# ---------------------------------------------------------------------------
# HTML Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request, admin: str = Depends(require_admin), db: Session = Depends(get_db)
):
    overview = dashboard.get_overview(db)
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "admin": admin, "overview": overview}
    )


@app.get("/tenants", response_class=HTMLResponse)
def tenants_page(
    request: Request,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    search: str | None = Query(None),
    plan: str | None = Query(None),
    status: str | None = Query(None),
    country: str | None = Query(None),
):
    data = tenants.list_tenants(
        db, page=page, search=search, plan=plan, status=status, country=country
    )
    countries = tenants.get_countries(db)
    return templates.TemplateResponse(
        "tenants/list.html",
        {
            "request": request,
            "admin": admin,
            "data": data,
            "countries": countries,
            "filters": {
                "search": search or "",
                "plan": plan or "",
                "status": status or "",
                "country": country or "",
            },
        },
    )


@app.get("/tenants/{tenant_id}", response_class=HTMLResponse)
def tenant_detail_page(
    request: Request,
    tenant_id: str,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    detail = tenants.get_tenant_detail(db, tenant_id)
    if not detail:
        return HTMLResponse("Tenant not found", status_code=404)
    return templates.TemplateResponse(
        "tenants/detail.html", {"request": request, "admin": admin, "tenant": detail}
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(
    request: Request, admin: str = Depends(require_admin), db: Session = Depends(get_db)
):
    analytics = users.get_user_analytics(db)
    return templates.TemplateResponse(
        "users.html", {"request": request, "admin": admin, "analytics": analytics}
    )


@app.get("/geography", response_class=HTMLResponse)
def geography_page(request: Request, admin: str = Depends(require_admin)):
    return templates.TemplateResponse("geography.html", {"request": request, "admin": admin})


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request, admin: str = Depends(require_admin)):
    return templates.TemplateResponse("export.html", {"request": request, "admin": admin})


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------
@app.get("/api/stats/overview")
def api_overview(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard.get_overview(db)


@app.get("/api/stats/plan-distribution")
def api_plan_distribution(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard.get_plan_distribution(db)


@app.get("/api/stats/subscription-status")
def api_subscription_status(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard.get_subscription_status(db)


@app.get("/api/stats/growth")
def api_growth(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard.get_growth(db)


@app.get("/api/stats/top-tenants")
def api_top_tenants(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return dashboard.get_top_tenants(db)


@app.get("/api/tenants")
def api_tenants(
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    search: str | None = Query(None),
    plan: str | None = Query(None),
    status: str | None = Query(None),
    country: str | None = Query(None),
):
    return tenants.list_tenants(
        db, page=page, per_page=per_page, search=search, plan=plan, status=status, country=country
    )


@app.patch("/api/tenants/{tenant_id}")
async def api_update_tenant(
    tenant_id: str,
    request: Request,
    admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    body = await request.json()
    result = tenants.update_tenant(db, tenant_id, body)
    if not result:
        return JSONResponse({"error": "Tenant not found"}, status_code=404)
    return result


@app.get("/api/tenants/{tenant_id}/users")
def api_tenant_users(
    tenant_id: str, admin: str = Depends(require_admin), db: Session = Depends(get_db)
):
    detail = tenants.get_tenant_detail(db, tenant_id)
    if not detail:
        return JSONResponse({"error": "Tenant not found"}, status_code=404)
    return detail["users"]


@app.post("/api/users/{user_id}/resend-verification")
def api_resend_verification(
    user_id: str, admin: str = Depends(require_admin), db: Session = Depends(get_db)
):
    import httpx

    from app.db.models import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    if user.is_email_verified:
        return JSONResponse({"error": "Email already verified"}, status_code=400)

    # Call the main app's resend-verification endpoint internally
    try:
        resp = httpx.post(
            "http://flyroom-app:8000/api/auth/resend-verification",
            json={"email": user.email},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        return JSONResponse({"error": f"Failed to contact app: {e}"}, status_code=502)

    if not resp.is_success:
        return JSONResponse(
            {"error": data.get("detail", "Send failed")}, status_code=resp.status_code
        )
    return {"message": f"Verification email sent to {user.email}"}


@app.get("/api/geography/tenants")
def api_geography(admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    from app.db.models import Tenant

    rows = (
        db.query(
            Tenant.id,
            Tenant.name,
            Tenant.city,
            Tenant.country,
            Tenant.latitude,
            Tenant.longitude,
            Tenant.plan,
        )
        .filter(Tenant.latitude.isnot(None), Tenant.longitude.isnot(None))
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "city": r.city,
            "country": r.country,
            "lat": r.latitude,
            "lng": r.longitude,
            "plan": r.plan.value if r.plan else None,
        }
        for r in rows
    ]


@app.post("/api/export/sql")
def api_export_sql(
    admin: str = Depends(require_admin),
    compress: bool = Query(False),
):
    filename = f"flyroom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    media_type = "application/sql"
    if compress:
        filename += ".gz"
        media_type = "application/gzip"

    return StreamingResponse(
        export.stream_sql_dump(compress=compress),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
