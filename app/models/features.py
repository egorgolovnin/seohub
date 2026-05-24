from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.sql import func
from app.database import Base


class RefLink(Base):
    __tablename__ = "ref_links"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)  # telegram user id
    url = Column(String(500), nullable=False)
    program_name = Column(String(200))
    geo = Column(String(50))
    last_status = Column(String(20), default="unknown")  # ok, redirect_changed, dead, suspicious
    last_redirect_url = Column(String(500))
    last_redirect_chain = Column(JSON)  # full redirect chain
    last_checked_at = Column(DateTime)
    check_count = Column(Integer, default=0)
    alerts = Column(JSON, default=list)  # list of alert messages
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class RefLinkCheck(Base):
    __tablename__ = "ref_link_checks"
    id = Column(Integer, primary_key=True)
    link_id = Column(Integer, nullable=False, index=True)
    status_code = Column(Integer)
    final_url = Column(String(500))
    redirect_chain = Column(JSON)
    response_time_ms = Column(Integer)
    issues = Column(JSON, default=list)  # list of detected issues
    checked_at = Column(DateTime, server_default=func.now())


class PartnerStatsUpload(Base):
    __tablename__ = "partner_stats_uploads"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    program_name = Column(String(200))
    geo = Column(String(50))
    period = Column(String(50))  # e.g. "2026-04"
    # Raw stats from PP
    clicks = Column(Integer)
    registrations = Column(Integer)
    ftd = Column(Integer)
    deposits_sum = Column(Float)
    ggr = Column(Float)
    commission = Column(Float)
    model = Column(String(20))  # CPA, RS, Hybrid
    # Computed metrics
    click_to_reg = Column(Float)  # registrations / clicks
    reg_to_ftd = Column(Float)  # ftd / registrations
    avg_deposit = Column(Float)  # deposits_sum / ftd
    ggr_per_ftd = Column(Float)  # ggr / ftd
    # Analysis results
    analysis = Column(JSON)  # full analysis from AI or rules
    risk_score = Column(Float)  # 0-10, higher = more suspicious
    flags = Column(JSON, default=list)  # list of red flags
    created_at = Column(DateTime, server_default=func.now())
