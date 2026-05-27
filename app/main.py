import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from aiogram.types import Update
from app.config import get_settings
from app.database import async_session, init_db
from app.api.routes import router as api_router
from app.bot.main import get_bot, create_dispatcher
from app.services.rates import get_cpa_rates
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")
dp = create_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bot = get_bot()
    settings = get_settings()

    # Register bot commands menu
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="rates", description="Ставки по ГЕО (DE, Германия...)"),
        BotCommand(command="cpa", description="Все CPA ставки"),
        BotCommand(command="check", description="Проверка ссылки — цепочка редиректов"),
        BotCommand(command="addlink", description="Добавить ссылку на мониторинг"),
        BotCommand(command="mylinks", description="Мои ссылки"),
        BotCommand(command="deletelink", description="Удалить ссылку"),
        BotCommand(command="report", description="Сводка по всем ссылкам"),
        BotCommand(command="analyze", description="Антишейв — скриншот или текст из ПП"),
        BotCommand(command="stats", description="📊 Аналитика (админ)"),
        BotCommand(command="help", description="Помощь"),
    ])

    # Set webhook for Railway (or use polling for dev)
    if settings.app_env == "production":
        # Webhook mode
        webhook_url = f"https://seohub-production.up.railway.app/webhook"
        await bot.set_webhook(webhook_url)
        logger.info(f"Webhook set: {webhook_url}")
    else:
        # Polling mode for local dev
        asyncio.create_task(dp.start_polling(bot))
        logger.info("Bot polling started")

    start_scheduler()
    yield

    if settings.app_env == "production":
        await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(title="SEOhub", lifespan=lifespan)
app.include_router(api_router)


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    bot = get_bot()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("app/templates/index.html", "r") as f:
        return HTMLResponse(f.read())


@app.get("/check", response_class=HTMLResponse)
async def check_page():
    with open("app/templates/check.html", "r") as f:
        return HTMLResponse(f.read())


@app.get("/rates", response_class=HTMLResponse)
async def rates_page(request: Request):
    async with async_session() as db:
        cpa = await get_cpa_rates(db)
    return templates.TemplateResponse(name="rates.html", request=request, context={
        "request": request,
        "cpa_rates": cpa,
        "total_geos": len(cpa),
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open("app/templates/admin.html", "r") as f:
        return HTMLResponse(f.read())


@app.post("/api/admin/login")
async def admin_login(request: Request):
    import hashlib
    data = await request.json()
    settings = get_settings()
    if data.get("login") == settings.admin_login and data.get("password") == settings.admin_password:
        token = hashlib.sha256(f"{settings.admin_login}:{settings.admin_password}".encode()).hexdigest()[:32]
        return {"ok": True, "token": token}
    return {"ok": False}


def _check_admin_token(token: str) -> bool:
    import hashlib
    settings = get_settings()
    expected = hashlib.sha256(f"{settings.admin_login}:{settings.admin_password}".encode()).hexdigest()[:32]
    return token == expected


@app.get("/api/admin/stats")
async def admin_stats(days: int = 1, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False, "error": "unauthorized"}
    from app.services.analytics import get_stats
    stats = await get_stats(days)
    return {"ok": True, "stats": stats}


@app.get("/api/admin/events")
async def admin_events(days: int = 1, token: str = "", limit: int = 50):
    if not _check_admin_token(token):
        return {"ok": False, "error": "unauthorized"}
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from app.models.models import AnalyticsEvent
    since = datetime.utcnow() - timedelta(days=days)
    async with async_session() as db:
        result = await db.execute(
            select(AnalyticsEvent)
            .where(AnalyticsEvent.created_at >= since)
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()
    return {
        "ok": True,
        "events": [
            {
                "time": e.created_at.strftime("%d.%m %H:%M") if e.created_at else "",
                "type": e.event_type,
                "username": e.username,
                "details": e.details,
                "cost": e.cost,
                "source": e.source,
            }
            for e in events
        ]
    }
