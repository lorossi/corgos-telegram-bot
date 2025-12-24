"""This module contains unit tests for the telegram module."""

import unittest
from contextlib import contextmanager
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from corgos_telegram_bot.modules.telegram import Telegram


class TestTelegramModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Telegram module."""

    async def asyncSetUp(self) -> None:
        """Set up the Telegram instance for testing."""
        self.settings_path = "tests/data/telegram_unit_test_settings.json"

    @contextmanager
    def mockTelegramDependencies(self) -> Generator:
        """Mock dependencies for the Telegram module."""
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

            mock_telegram = MagicMock()
            mock_telegram.initialize = AsyncMock()
            mock_telegram.start = AsyncMock()
            mock_telegram.stop = AsyncMock()
            mock_telegram.shutdown = AsyncMock()
            mock_telegram.updater = mock_updater

            mock_builder.return_value = mock_app_builder

            mock_app_builder.token.return_value = mock_app_builder
            mock_app_builder.build.return_value = mock_telegram

            mock_reddit.return_value = AsyncMock()

            yield mock_telegram, mock_reddit

    async def testInitializeTelegram(self) -> None:
        """Test initializing the Telegram instance."""
        Telegram(settings_path=self.settings_path)

    async def testTelegramStartStop(self) -> None:
        """Test starting and stopping the Telegram instance."""
        telegram = Telegram(settings_path=self.settings_path)
        with self.mockTelegramDependencies():
            await telegram.start()
            await telegram.stop()
