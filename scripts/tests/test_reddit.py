"""This module contains unit tests for the reddit module."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts.modules.reddit import EmptyQueueException, Reddit


class TestRedditModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Reddit module."""

    async def asyncSetUp(self) -> None:
        """Set up the Reddit instance for testing."""
        self.settings_path = "scripts/tests/data/reddit_unit_test_settings.json"

    async def testInitializeReddit(self) -> None:
        """Test initializing the Reddit instance."""
        reddit = Reddit(settings_path=self.settings_path)

        with patch(
            "scripts.modules.reddit.asyncpraw.Reddit",
            new_callable=AsyncMock,
        ) as mock_asyncpraw:
            await reddit.start()
            mock_asyncpraw.assert_called_once()

        # test that the queue is empty and no url is loaded
        with self.assertRaises(EmptyQueueException):
            await reddit.getUrl()

        self.assertTrue(await reddit.isQueueEmpty(), 0)
