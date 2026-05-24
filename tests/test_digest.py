import pytest
from datetime import datetime, timedelta
from app.services.digest import (
    save_raw_posts, get_pending_posts, approve_post, reject_post,
    mark_published, get_week_posts, add_channel, get_active_channels,
    format_digest_post, format_weekly_digest,
)
from app.models.models import DigestPost


@pytest.mark.asyncio
async def test_save_raw_posts(db):
    posts = [
        {"channel_name": "Test", "channel_username": "test", "text": "Post 1 about SEO", "date": datetime.utcnow(), "message_id": 1},
        {"channel_name": "Test", "channel_username": "test", "text": "Post 2 about gambling", "date": datetime.utcnow(), "message_id": 2},
    ]
    saved = await save_raw_posts(db, posts)
    assert saved == 2


@pytest.mark.asyncio
async def test_save_raw_posts_dedup(db):
    posts = [
        {"channel_name": "Test", "channel_username": "test_dedup", "text": "Unique post", "date": datetime.utcnow(), "message_id": 100},
    ]
    saved1 = await save_raw_posts(db, posts)
    saved2 = await save_raw_posts(db, posts)
    assert saved1 == 1
    assert saved2 == 0


@pytest.mark.asyncio
async def test_get_pending_posts(db):
    posts = [
        {"channel_name": "Ch1", "channel_username": "ch1", "text": "Pending post", "date": datetime.utcnow(), "message_id": 200},
    ]
    await save_raw_posts(db, posts)
    pending = await get_pending_posts(db)
    assert len(pending) >= 1
    assert pending[0].status == "pending"


@pytest.mark.asyncio
async def test_approve_reject_flow(db):
    posts = [
        {"channel_name": "Flow", "channel_username": "flow", "text": "Flow test post", "date": datetime.utcnow(), "message_id": 300},
    ]
    await save_raw_posts(db, posts)
    pending = await get_pending_posts(db)
    post_id = pending[0].id

    result = await approve_post(db, post_id)
    assert result is True

    # Re-fetch
    from sqlalchemy import select
    r = await db.execute(select(DigestPost).where(DigestPost.id == post_id))
    post = r.scalar_one()
    assert post.status == "approved"


@pytest.mark.asyncio
async def test_reject_post(db):
    posts = [
        {"channel_name": "Rej", "channel_username": "rej", "text": "Reject test", "date": datetime.utcnow(), "message_id": 400},
    ]
    await save_raw_posts(db, posts)
    pending = await get_pending_posts(db)
    post_id = pending[0].id
    result = await reject_post(db, post_id)
    assert result is True


@pytest.mark.asyncio
async def test_approve_nonexistent(db):
    result = await approve_post(db, 99999)
    assert result is False


@pytest.mark.asyncio
async def test_mark_published(db):
    posts = [
        {"channel_name": "Pub", "channel_username": "pub", "text": "Publish test", "date": datetime.utcnow(), "message_id": 500},
    ]
    await save_raw_posts(db, posts)
    pending = await get_pending_posts(db)
    post_id = pending[0].id
    await approve_post(db, post_id)
    result = await mark_published(db, post_id)
    assert result is True


@pytest.mark.asyncio
async def test_add_and_get_channels(db):
    ch = await add_channel(db, "123456", "Test Channel", "testchannel", "seo")
    assert ch.name == "Test Channel"

    channels = await get_active_channels(db)
    assert len(channels) >= 1
    assert any(c.username == "testchannel" for c in channels)


def test_format_digest_post():
    post = DigestPost(
        summary="Кейс: залив 200K в BR за 4 месяца",
        category="case",
        channel_name="SEO Chat",
        original_date=datetime(2026, 4, 15),
        original_text="test",
    )
    text = format_digest_post(post)
    assert "Кейс" in text
    assert "SEO Chat" in text


def test_format_weekly_digest():
    posts = [
        DigestPost(summary="Post 1", category="case", original_text="t"),
        DigestPost(summary="Post 2", category="news", original_text="t"),
    ]
    text = format_weekly_digest("Итоги: хорошая неделя", posts)
    assert "Итоги недели" in text
    assert "2 постов" in text
