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
from app.services.rates import get_cpa_rates, get_rs_rates
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
    return HTMLResponse("<h1>SEOhub</h1><p><a href='/rates'>Ставки CPA/RS</a></p>")


@app.get("/rates", response_class=HTMLResponse)
async def rates_page(request: Request):
    async with async_session() as db:
        cpa = await get_cpa_rates(db)
        rs = await get_rs_rates(db)
    total_points = sum(r["points"] or 0 for r in cpa) + sum(r["points"] or 0 for r in rs)
    return templates.TemplateResponse(name="rates.html", request=request, context={
        "request": request,
        "cpa_rates": cpa,
        "rs_rates": rs,
        "total_points": total_points,
        "total_geos": len(cpa) + len(rs),
        "total_pp": 34,
    })


@app.get("/health")
async def health():
    return {"status": "ok"}
