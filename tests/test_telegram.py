"""This module contains unit tests for the telegram module."""

import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from corgos_telegram_bot.modules.telegram import Telegram


class TestTelegramModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Telegram module."""

    async def asyncSetUp(self) -> None:
        """Set up the Telegram instance for testing."""
        self.settings_path = "tests/data/telegram_unit_test_settings.json"

    async def testInitializeTelegram(self) -> None:
        """Test initializing the Telegram instance."""
        Telegram(settings_path=self.settings_path)

    async def testTelegramStartStop(self) -> None:
        """Test starting and stopping the Telegram instance."""
        telegram = Telegram(settings_path=self.settings_path)

        with (
            patch("telegram.ext.Application.builder") as mock_builder,
            patch(
                "corgos_telegram_bot.modules.reddit.asyncpraw.Reddit",
                new_callable=Mock(),
            ) as mock_reddit,
        ):
            mock_app_builder = MagicMock()

            mock_updater = AsyncMock()
            mock_updater.start_polling = AsyncMock()

            mock_app = MagicMock()
            mock_app.initialize = AsyncMock()
            mock_app.start = AsyncMock()
            mock_app.stop = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.updater = mock_updater

            mock_builder.return_value = mock_app_builder

            mock_app_builder.token.return_value = mock_app_builder
            mock_app_builder.build.return_value = mock_app

            mock_reddit.return_value = AsyncMock()

            await telegram.start()
            await telegram.stop()
