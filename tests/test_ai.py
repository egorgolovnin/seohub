import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.ai import score_post, generate_weekly_summary


@pytest.mark.asyncio
async def test_score_post_no_key():
    with patch("app.services.ai.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(anthropic_api_key="")
        result = await score_post("test post")
        assert result is None


@pytest.mark.asyncio
async def test_score_post_success():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"score": 8.0, "category": "case", "summary": "Хороший кейс"}')]

    with patch("app.services.ai.get_settings") as mock_settings, \
         patch("app.services.ai.AsyncAnthropic") as mock_client_cls:
        mock_settings.return_value = MagicMock(anthropic_api_key="test-key")
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await score_post("Залили 200K в BR за 4 месяца")
        assert result is not None
        assert result["score"] == 8.0
        assert result["category"] == "case"


@pytest.mark.asyncio
async def test_generate_weekly_no_key():
    with patch("app.services.ai.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(anthropic_api_key="")
        result = await generate_weekly_summary("test")
        assert result is None
