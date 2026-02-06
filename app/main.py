"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import Cookie, Depends, FastAPI, Request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.utils import decode_access_token
from app.config import get_settings
from app.db.database import get_db, init_db
from app.db.models import User

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events.

    Args:
        app: FastAPI application instance.
    """
    # Startup
    init_db()
    yield
    # Shutdown (cleanup if needed)


app = FastAPI(
    title=settings.app_name,
    description="A SaaS web application for managing Drosophila stocks in research laboratories",
    version="0.1.0",
    lifespan=lifespan,
    debug=settings.debug,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates with global context
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_name"] = settings.app_name


# Import and include routers
from app.auth.router import router as auth_router
from app.crosses.router import router as crosses_router
from app.flips.router import router as flips_router
from app.imports.router import router as imports_router
from app.labels.router import router as labels_router
from app.organizations.router import router as organizations_router
from app.plugins.router import router as plugins_router
from app.requests.router import router as requests_router
from app.stocks.router import router as stocks_router
from app.tags.router import router as tags_router
from app.tenants.router import router as tenants_router
from app.trays.router import router as trays_router

# API routes
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(stocks_router, prefix="/api/stocks", tags=["stocks"])
app.include_router(crosses_router, prefix="/api/crosses", tags=["crosses"])
app.include_router(labels_router, prefix="/api/labels", tags=["labels"])
app.include_router(imports_router, prefix="/api/imports", tags=["imports"])
app.include_router(tenants_router, prefix="/api/admin", tags=["admin"])
app.include_router(plugins_router, prefix="/api/plugins", tags=["plugins"])
app.include_router(organizations_router, prefix="/api/organizations", tags=["organizations"])
app.include_router(trays_router, prefix="/api/trays", tags=["trays"])
app.include_router(requests_router, prefix="/api/requests", tags=["requests"])
app.include_router(tags_router, prefix="/api/tags", tags=["tags"])
app.include_router(flips_router, prefix="/api/flips", tags=["flips"])


def get_current_user_from_cookie(
    db: Session,
    access_token: str | None = None,
) -> User | None:
    """Get current user from access token cookie.

    Args:
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        User if authenticated and approved, None otherwise.
    """
    from app.db.models import UserStatus

    if not access_token:
        return None
    try:
        token_data = decode_access_token(access_token)
        if not token_data:
            return None
        user_id = token_data.user_id
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.is_active and user.status == UserStatus.APPROVED:
            return user
    except Exception:
        pass
    return None


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the home page / dashboard.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse: Dashboard or redirect to login.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    # Get dashboard stats
    from app.db.models import Cross, CrossStatus, Stock, Tag

    stats = {
        "total_stocks": db.query(Stock)
        .filter(
            Stock.tenant_id == current_user.tenant_id,
            Stock.is_active,
        )
        .count(),
        "active_crosses": db.query(Cross)
        .filter(
            Cross.tenant_id == current_user.tenant_id,
            Cross.status.in_([CrossStatus.PLANNED, CrossStatus.IN_PROGRESS]),
        )
        .count(),
        "total_tags": db.query(Tag)
        .filter(
            Tag.tenant_id == current_user.tenant_id,
        )
        .count(),
        "recent_updates": db.query(Stock)
        .filter(
            Stock.tenant_id == current_user.tenant_id,
        )
        .count(),  # Simplified for now
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Dashboard",
            "current_user": current_user,
            "stats": stats,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: Rendered template.
    """
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "title": "Login"},
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, invite: str | None = None):
    """Render the registration page.

    Args:
        request: FastAPI request object.
        invite: Optional invitation token from query params.

    Returns:
        HTMLResponse: Rendered template.
    """
    return templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "title": "Register",
            "invitation_token": invite,
        },
    )


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(request: Request, token: str | None = None):
    """Render the email verification page.

    This page handles the verification when user clicks the link in their email.

    Args:
        request: FastAPI request object.
        token: Verification token from query params.

    Returns:
        HTMLResponse: Rendered template.
    """
    return templates.TemplateResponse(
        "auth/verify_email.html",
        {
            "request": request,
            "title": "Verify Email",
            "token": token,
        },
    )


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Render the forgot password page.

    Args:
        request: FastAPI request object.

    Returns:
        HTMLResponse: Rendered template.
    """
    return templates.TemplateResponse(
        "auth/forgot_password.html",
        {"request": request, "title": "Forgot Password"},
    )


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str | None = None):
    """Render the password reset page.

    Args:
        request: FastAPI request object.
        token: Password reset token from query params.

    Returns:
        HTMLResponse: Rendered template.
    """
    return templates.TemplateResponse(
        "auth/reset_password.html",
        {
            "request": request,
            "title": "Reset Password",
            "token": token or "",
        },
    )


@app.get("/stocks", response_class=HTMLResponse)
async def stocks_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the stocks list page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "stocks/list.html",
        {
            "request": request,
            "title": "Stocks",
            "current_user": current_user,
        },
    )


@app.get("/stocks/new", response_class=HTMLResponse)
async def stocks_new_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the new stock form page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "stocks/new.html",
        {
            "request": request,
            "title": "Add Stock",
            "current_user": current_user,
        },
    )


@app.get("/stocks/import", response_class=HTMLResponse)
async def stocks_import_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the stocks import page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "stocks/import.html",
        {
            "request": request,
            "title": "Import Stocks",
            "current_user": current_user,
        },
    )


@app.get("/stocks/import-bdsc", response_class=HTMLResponse)
async def stocks_import_bdsc_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the BDSC import page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "stocks/import_bdsc.html",
        {
            "request": request,
            "title": "Import from BDSC",
            "current_user": current_user,
        },
    )


@app.get("/stocks/{stock_id}", response_class=HTMLResponse)
async def stock_detail_page(
    stock_id: str,
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the stock detail page.

    Args:
        stock_id: Stock ID from URL.
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "stocks/detail.html",
        {
            "request": request,
            "title": "Stock Details",
            "current_user": current_user,
            "stock_id": stock_id,
        },
    )


@app.get("/crosses", response_class=HTMLResponse)
async def crosses_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the crosses list page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "crosses/list.html",
        {
            "request": request,
            "title": "Crosses",
            "current_user": current_user,
        },
    )


@app.get("/crosses/new", response_class=HTMLResponse)
async def crosses_new_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the new cross form page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "crosses/new.html",
        {
            "request": request,
            "title": "Plan Cross",
            "current_user": current_user,
        },
    )


@app.get("/crosses/{cross_id}", response_class=HTMLResponse)
async def cross_detail_page(
    cross_id: str,
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the cross detail page.

    Args:
        cross_id: Cross ID from URL.
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "crosses/detail.html",
        {
            "request": request,
            "title": "Cross Details",
            "current_user": current_user,
            "cross_id": cross_id,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the user settings page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "title": "Settings",
            "current_user": current_user,
        },
    )


@app.get("/labels", response_class=HTMLResponse)
async def labels_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the labels page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "labels/index.html",
        {
            "request": request,
            "title": "Labels",
            "current_user": current_user,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the admin panel page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    from app.db.models import UserRole

    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    # Only admins can access
    if current_user.role != UserRole.ADMIN:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "admin/index.html",
        {
            "request": request,
            "title": "Admin Panel",
            "current_user": current_user,
        },
    )


@app.get("/trays", response_class=HTMLResponse)
async def trays_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the trays management page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "trays/list.html",
        {
            "request": request,
            "title": "Trays",
            "current_user": current_user,
        },
    )


@app.get("/trays/{tray_id}", response_class=HTMLResponse)
async def tray_detail_page(
    tray_id: str,
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the tray detail page.

    Args:
        tray_id: Tray ID from URL.
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "trays/detail.html",
        {
            "request": request,
            "title": "Tray Details",
            "current_user": current_user,
            "tray_id": tray_id,
        },
    )


@app.get("/tags", response_class=HTMLResponse)
async def tags_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the tags management page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "tags/list.html",
        {
            "request": request,
            "title": "Tags",
            "current_user": current_user,
        },
    )


@app.get("/exchange", response_class=HTMLResponse)
async def exchange_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the public stocks exchange page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "exchange/browse.html",
        {
            "request": request,
            "title": "Stock Exchange",
            "current_user": current_user,
        },
    )


@app.get("/exchange/requests", response_class=HTMLResponse)
async def my_requests_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the my stock requests page.

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "exchange/requests.html",
        {
            "request": request,
            "title": "My Requests",
            "current_user": current_user,
        },
    )


@app.get("/admin/requests", response_class=HTMLResponse)
async def admin_requests_page(
    request: Request,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """Render the incoming stock requests page (admin).

    Args:
        request: FastAPI request object.
        db: Database session.
        access_token: JWT access token from cookie.

    Returns:
        HTMLResponse or RedirectResponse.
    """
    from app.db.models import UserRole

    current_user = get_current_user_from_cookie(db, access_token)
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    if current_user.role != UserRole.ADMIN:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "admin/requests.html",
        {
            "request": request,
            "title": "Incoming Requests",
            "current_user": current_user,
        },
    )


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/Kubernetes.

    Returns:
        dict: Health status.
    """
    return {"status": "healthy", "app": settings.app_name}


@app.get("/manifest.json")
async def manifest():
    """Serve dynamic PWA manifest with configurable app name.

    Returns:
        dict: PWA manifest JSON.
    """
    return {
        "name": f"{settings.app_name} - Drosophila Stock Management",
        "short_name": settings.app_name,
        "description": "Manage your Drosophila fly stocks efficiently",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#2563eb",
        "orientation": "portrait-primary",
        "scope": "/",
        "lang": "en",
        "icons": [
            {
                "src": "/static/icons/icon-72.png",
                "sizes": "72x72",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-96.png",
                "sizes": "96x96",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-128.png",
                "sizes": "128x128",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-144.png",
                "sizes": "144x144",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-152.png",
                "sizes": "152x152",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-384.png",
                "sizes": "384x384",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "categories": ["productivity", "utilities"],
        "shortcuts": [
            {"name": "Add Stock", "url": "/stocks/new", "description": "Add a new fly stock"},
            {"name": "View Stocks", "url": "/stocks", "description": "View all stocks"},
            {"name": "Plan Cross", "url": "/crosses/new", "description": "Plan a new cross"},
        ],
    }


@app.get("/sw.js")
async def service_worker():
    """Serve dynamic service worker with configurable app name.

    Returns:
        Response: JavaScript service worker file.
    """
    from fastapi.responses import Response

    # Generate cache name from app name (lowercase, no spaces)
    cache_name = settings.app_name.lower().replace(" ", "-") + "-v1"
    db_name = settings.app_name.lower().replace(" ", "-") + "-offline"

    sw_content = f"""/**
 * {settings.app_name} Service Worker
 * Provides offline support and caching
 */

const CACHE_NAME = '{cache_name}';
const APP_NAME = '{settings.app_name}';
const OFFLINE_URL = '/offline.html';

// Static assets to cache immediately
const STATIC_ASSETS = [
    '/',
    '/static/css/main.css',
    '/static/js/app.js',
    '/manifest.json',
    '/login',
    '/register'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {{
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {{
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            }})
            .then(() => self.skipWaiting())
    );
}});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {{
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {{
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => {{
                            console.log('[SW] Deleting old cache:', name);
                            return caches.delete(name);
                        }})
                );
            }})
            .then(() => self.clients.claim())
    );
}});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {{
    const {{ request }} = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') {{
        return;
    }}

    // Skip API requests (don't cache)
    if (url.pathname.startsWith('/api/')) {{
        event.respondWith(
            fetch(request)
                .catch(() => {{
                    // Return cached response for offline API calls
                    return new Response(
                        JSON.stringify({{ error: 'You are offline' }}),
                        {{
                            status: 503,
                            headers: {{ 'Content-Type': 'application/json' }}
                        }}
                    );
                }})
        );
        return;
    }}

    // For HTML pages - network first, cache fallback
    if (request.headers.get('Accept')?.includes('text/html')) {{
        event.respondWith(
            fetch(request)
                .then((response) => {{
                    // Cache successful responses
                    if (response.ok) {{
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {{
                            cache.put(request, responseClone);
                        }});
                    }}
                    return response;
                }})
                .catch(() => {{
                    return caches.match(request)
                        .then((cachedResponse) => {{
                            return cachedResponse || caches.match(OFFLINE_URL);
                        }});
                }})
        );
        return;
    }}

    // For static assets - cache first, network fallback
    event.respondWith(
        caches.match(request)
            .then((cachedResponse) => {{
                if (cachedResponse) {{
                    // Return cached response immediately
                    // Also fetch from network to update cache
                    fetch(request)
                        .then((networkResponse) => {{
                            if (networkResponse.ok) {{
                                caches.open(CACHE_NAME).then((cache) => {{
                                    cache.put(request, networkResponse);
                                }});
                            }}
                        }})
                        .catch(() => {{}});

                    return cachedResponse;
                }}

                // No cache, fetch from network
                return fetch(request)
                    .then((response) => {{
                        if (response.ok) {{
                            const responseClone = response.clone();
                            caches.open(CACHE_NAME).then((cache) => {{
                                cache.put(request, responseClone);
                            }});
                        }}
                        return response;
                    }});
            }})
    );
}});

// Background sync for offline mutations
self.addEventListener('sync', (event) => {{
    if (event.tag === 'sync-stocks') {{
        event.waitUntil(syncStocks());
    }}
}});

// Sync pending stock changes when online
async function syncStocks() {{
    const db = await openDatabase();
    const pendingChanges = await getPendingChanges(db);

    for (const change of pendingChanges) {{
        try {{
            const response = await fetch(change.url, {{
                method: change.method,
                headers: change.headers,
                body: JSON.stringify(change.body)
            }});

            if (response.ok) {{
                await removePendingChange(db, change.id);
            }}
        }} catch (error) {{
            console.error('[SW] Sync failed for:', change, error);
        }}
    }}
}}

// IndexedDB helpers for offline sync
function openDatabase() {{
    return new Promise((resolve, reject) => {{
        const request = indexedDB.open('{db_name}', 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {{
            const db = event.target.result;
            if (!db.objectStoreNames.contains('pending-changes')) {{
                db.createObjectStore('pending-changes', {{ keyPath: 'id', autoIncrement: true }});
            }}
        }};
    }});
}}

function getPendingChanges(db) {{
    return new Promise((resolve, reject) => {{
        const transaction = db.transaction(['pending-changes'], 'readonly');
        const store = transaction.objectStore('pending-changes');
        const request = store.getAll();

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);
    }});
}}

function removePendingChange(db, id) {{
    return new Promise((resolve, reject) => {{
        const transaction = db.transaction(['pending-changes'], 'readwrite');
        const store = transaction.objectStore('pending-changes');
        const request = store.delete(id);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve();
    }});
}}

// Handle push notifications
self.addEventListener('push', (event) => {{
    if (event.data) {{
        const data = event.data.json();

        event.waitUntil(
            self.registration.showNotification(data.title || APP_NAME, {{
                body: data.body || 'You have a new notification',
                icon: '/static/icons/icon-192.png',
                badge: '/static/icons/icon-72.png',
                data: data.url || '/'
            }})
        );
    }}
}});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {{
    event.notification.close();

    event.waitUntil(
        clients.openWindow(event.notification.data)
    );
}});

console.log('[SW] Service Worker loaded');
"""

    return Response(
        content=sw_content,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
