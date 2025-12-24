"""This module contains unit tests for the reddit module."""

import unittest
from contextlib import contextmanager
from typing import Generator
from unittest.mock import AsyncMock, Mock, patch

from corgos_telegram_bot.modules.reddit import EmptyQueueException, Reddit


class TestRedditModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Reddit module."""

    async def asyncSetUp(self) -> None:
        """Set up the Reddit instance for testing."""
        self.settings_path = "tests/data/reddit_unit_test_settings.json"

    @contextmanager
    def mockRedditDependencies(self) -> Generator:
        """Mock dependencies for the Reddit module."""
        with patch(
            "corgos_telegram_bot.modules.reddit.asyncpraw.Reddit",
            new_callable=Mock(),
        ) as mock_reddit:
            mock_reddit_instance = AsyncMock()
            mock_reddit.return_value = mock_reddit_instance

            yield mock_reddit_instance

    async def testInitializeReddit(self) -> None:
        """Test initializing the Reddit instance."""
        reddit = Reddit(settings_path=self.settings_path)
        self.assertTrue(await reddit.isQueueEmpty())
        self.assertFalse(reddit.is_loading)

    async def testRedditStartStop(self) -> None:
        """Test starting and stopping the Reddit instance."""
        reddit = Reddit(settings_path=self.settings_path)

        with self.mockRedditDependencies():
            await reddit.start()
            await reddit.stop()

    async def testRedditGetEmptyQueue(self) -> None:
        """Test getting an empty Reddit queue."""
        reddit = Reddit(settings_path=self.settings_path)
        with self.assertRaises(EmptyQueueException):
            await reddit.getUrl()
