FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir "fastapi[standard]" "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg aiogram jinja2 openpyxl httpx anthropic apscheduler telethon python-dotenv pydantic-settings

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
