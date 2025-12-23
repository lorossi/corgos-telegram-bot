"""This module contains unit tests for the reddit module."""

import unittest

from corgos_telegram_bot.modules.reddit import Reddit


class TestRedditModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Reddit module."""

    async def asyncSetUp(self) -> None:
        """Set up the Reddit instance for testing."""
        self.settings_path = "tests/data/reddit_unit_test_settings.json"

    async def testInitializeReddit(self) -> None:
        """Test initializing the Reddit instance."""
        Reddit(settings_path=self.settings_path)
