"""Reload CPA rates with correct data (only real GEO codes, no UNKNOWN/TIER/etc)."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, async_session, init_db
from app.models.models import GeoRateCPA

# Canonical CPA rates — same as were on the site
CPA_RATES = [
    ("NL", 120, 330, 650),
    ("DK", 130, 300, 560),
    ("NO", 130, 300, 400),
    ("CH", 120, 290, 520),
    ("IE", 130, 280, 500),
    ("DE", 120, 260, 550),
    ("SE", 130, 260, 400),
    ("AT", 130, 260, 400),
    ("AE", 200, 250, 300),
    ("BE", 160, 250, 550),
    ("SA", 150, 250, 380),
    ("AU", 120, 250, 500),
    ("CA", 120, 250, 500),
    ("ES", 120, 240, 450),
    ("FR", 120, 240, 500),
    ("SK", 180, 240, 350),
    ("IT", 120, 220, 350),
    ("UK", 120, 220, 500),
    ("HR", 200, 260, 350),
    ("SI", 120, 220, 300),
    ("CZ", 120, 220, 350),
    ("GR", 120, 210, 400),
    ("FI", 120, 210, 400),
    ("NZ", 120, 210, 360),
    ("JP", 130, 200, 340),
    ("HU", 120, 180, 350),
    ("PL", 120, 170, 350),
    ("PT", 120, 170, 300),
    ("US", 120, 160, 300),
    ("SG", 120, 160, 250),
    ("EE", 100, 150, 180),
    ("RU", 35, 140, 250),
    ("KZ", 23, 120, 200),
    ("BY", 25, 120, 200),
    ("UZ", 20, 90, 150),
    ("BR", 6, 70, 120),
    ("CL", 15, 70, 120),
    ("IN", 11, 70, 120),
    ("BD", 16, 70, 100),
    ("TR", 30, 60, 120),
    ("ZA", 5, 70, 100),
    ("MX", 5, 50, 80),
    ("AR", 13, 40, 80),
    ("TH", 15, 30, 50),
    ("CO", 20, 30, 50),
]


async def reload_cpa():
    await init_db()

    async with async_session() as db:
        # Clear old CPA data
        await db.execute(text("DELETE FROM geo_rates_cpa"))

        for geo, mn, avg, mx in CPA_RATES:
            db.add(GeoRateCPA(
                geo=geo,
                min_cpa=float(mn),
                avg_cpa=float(avg),
                max_cpa=float(mx),
                data_points=1,
                sources="seohub",
                programs="",
            ))

        await db.commit()
        print(f"✅ Loaded {len(CPA_RATES)} CPA rates (real GEOs only)")


if __name__ == "__main__":
    asyncio.run(reload_cpa())
