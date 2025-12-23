"""This module contains unit tests for the reddit module."""

import unittest

from corgos_telegram_bot.modules.reddit import EmptyQueueException, Reddit


class TestRedditModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Reddit module."""

    async def asyncSetUp(self) -> None:
        """Set up the Reddit instance for testing."""
        self.settings_path = "tests/data/reddit_unit_test_settings.json"

    async def testInitializeReddit(self) -> None:
        """Test initializing the Reddit instance."""
        reddit = Reddit(settings_path=self.settings_path)
        self.assertTrue(await reddit.isQueueEmpty())
        self.assertFalse(reddit.is_loading)

    async def testRedditGetEmptyQueue(self) -> None:
        """Test getting an empty Reddit queue."""
        reddit = Reddit(settings_path=self.settings_path)
        with self.assertRaises(EmptyQueueException):
            await reddit.getUrl()
