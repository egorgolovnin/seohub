"""Load rates data from seohub_rates_database.xlsx into PostgreSQL."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import text
from app.database import engine, async_session, init_db
from app.models.models import GeoRateCPA, GeoRateRS, RateRaw, PPCondition


async def load_rates(xlsx_path: str):
    await init_db()

    xl = pd.read_excel(xlsx_path, sheet_name=None)

    async with async_session() as db:
        # Clear existing data
        for table in ["geo_rates_cpa", "geo_rates_rs", "rates_raw", "pp_conditions"]:
            await db.execute(text(f"DELETE FROM {table}"))

        # CPA rates
        cpa_df = xl.get("CPA по ГЕО")
        if cpa_df is not None:
            for _, row in cpa_df.iterrows():
                db.add(GeoRateCPA(
                    geo=str(row.iloc[0]).strip(),
                    min_cpa=float(row.iloc[1]) if pd.notna(row.iloc[1]) else None,
                    avg_cpa=float(row.iloc[2]) if pd.notna(row.iloc[2]) else None,
                    max_cpa=float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    data_points=int(row.iloc[4]) if pd.notna(row.iloc[4]) else None,
                    sources=str(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    programs=str(row.iloc[6]) if pd.notna(row.iloc[6]) else None,
                ))
            print(f"Loaded {len(cpa_df)} CPA rates")

        # RS rates
        rs_df = xl.get("RevShare по ГЕО")
        if rs_df is not None:
            for _, row in rs_df.iterrows():
                db.add(GeoRateRS(
                    geo=str(row.iloc[0]).strip(),
                    min_rs=float(row.iloc[1]) if pd.notna(row.iloc[1]) else None,
                    avg_rs=float(row.iloc[2]) if pd.notna(row.iloc[2]) else None,
                    max_rs=float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    data_points=int(row.iloc[4]) if pd.notna(row.iloc[4]) else None,
                    sources=str(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    programs=str(row.iloc[6]) if pd.notna(row.iloc[6]) else None,
                ))
            print(f"Loaded {len(rs_df)} RS rates")

        # Raw data
        raw_df = xl.get("Все данные (raw)")
        if raw_df is not None:
            for _, row in raw_df.iterrows():
                db.add(RateRaw(
                    geo=str(row.iloc[0]).strip(),
                    rate_type=str(row.iloc[1]).strip(),
                    amount=float(row.iloc[2]) if pd.notna(row.iloc[2]) else None,
                    program=str(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    source=str(row.iloc[4]) if pd.notna(row.iloc[4]) else None,
                ))
            print(f"Loaded {len(raw_df)} raw records")

        # PP conditions
        pp_df = xl.get("ПП с условиями")
        if pp_df is not None:
            for _, row in pp_df.iterrows():
                db.add(PPCondition(
                    name=str(row.iloc[0]).strip(),
                    geos=str(row.iloc[1]) if pd.notna(row.iloc[1]) else None,
                    cpa_min=float(row.iloc[2]) if pd.notna(row.iloc[2]) else None,
                    cpa_max=float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                    rs_min=float(row.iloc[4]) if pd.notna(row.iloc[4]) else None,
                    rs_max=float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    records_count=int(row.iloc[6]) if pd.notna(row.iloc[6]) else None,
                    source=str(row.iloc[7]) if pd.notna(row.iloc[7]) else None,
                ))
            print(f"Loaded {len(pp_df)} PP conditions")

        await db.commit()
        print("✅ All data loaded successfully")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/seohub_rates_database.xlsx"
    asyncio.run(load_rates(path))
