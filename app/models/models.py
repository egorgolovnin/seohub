from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.sql import func
from app.database import Base


class GeoRateCPA(Base):
    __tablename__ = "geo_rates_cpa"
    id = Column(Integer, primary_key=True)
    geo = Column(String(20), nullable=False, index=True)
    min_cpa = Column(Float)
    avg_cpa = Column(Float)
    max_cpa = Column(Float)
    data_points = Column(Integer)
    sources = Column(Text)
    programs = Column(Text)


class GeoRateRS(Base):
    __tablename__ = "geo_rates_rs"
    id = Column(Integer, primary_key=True)
    geo = Column(String(20), nullable=False, index=True)
    min_rs = Column(Float)
    avg_rs = Column(Float)
    max_rs = Column(Float)
    data_points = Column(Integer)
    sources = Column(Text)
    programs = Column(Text)


class RateRaw(Base):
    __tablename__ = "rates_raw"
    id = Column(Integer, primary_key=True)
    geo = Column(String(20), nullable=False, index=True)
    rate_type = Column(String(5), nullable=False)  # CPA or RS
    amount = Column(Float)
    program = Column(String(200))
    source = Column(String(100))


class PPCondition(Base):
    __tablename__ = "pp_conditions"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    geos = Column(Text)
    cpa_min = Column(Float, nullable=True)
    cpa_max = Column(Float, nullable=True)
    rs_min = Column(Float, nullable=True)
    rs_max = Column(Float, nullable=True)
    records_count = Column(Integer)
    source = Column(String(100))


class DigestChannel(Base):
    __tablename__ = "digest_channels"
    id = Column(Integer, primary_key=True)
    channel_id = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    username = Column(String(100))
    category = Column(String(50))  # seo, news, tools, general
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class DigestPost(Base):
    __tablename__ = "digest_posts"
    id = Column(Integer, primary_key=True)
    channel_name = Column(String(200))
    channel_username = Column(String(100))
    original_text = Column(Text, nullable=False)
    original_date = Column(DateTime)
    original_message_id = Column(Integer)
    summary = Column(Text)  # AI-generated summary
    category = Column(String(50))  # case, guide, tool, news, insight
    importance_score = Column(Float)  # 0-10, AI-rated
    status = Column(String(20), default="pending")  # pending, approved, rejected, published
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class WeeklyDigest(Base):
    __tablename__ = "weekly_digests"
    id = Column(Integer, primary_key=True)
    week_start = Column(DateTime, nullable=False)
    week_end = Column(DateTime, nullable=False)
    summary = Column(Text)  # AI-generated weekly summary
    post_ids = Column(JSON)  # list of DigestPost ids included
    status = Column(String(20), default="pending")
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
