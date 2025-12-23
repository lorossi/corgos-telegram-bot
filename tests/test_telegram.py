"""This module contains unit tests for the telegram module."""

import unittest

from corgos_telegram_bot.modules.telegram import Telegram


class TestTelegramModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Telegram module."""

    async def asyncSetUp(self) -> None:
        """Set up the Telegram instance for testing."""
        self.settings_path = "tests/data/telegram_unit_test_settings.json"

    async def testInitializeTelegram(self) -> None:
        """Test initializing the Telegram instance."""
        Telegram(settings_path=self.settings_path)
