"""This module contains unit tests for the reddit module."""

import asyncio
import shutil
import tempfile
import unittest
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp

from corgos_telegram_bot.modules.reddit import EmptyQueueError, Reddit
from corgos_telegram_bot.modules.settings import SingletonMeta


def makeSubmission(url: str, **kwargs: Any) -> MagicMock:
    """Create a fake reddit submission.

    Args:
        url (str): url of the submission
        **kwargs (Any): attributes overriding the defaults

    Returns:
        MagicMock: the fake submission
    """
    submission = MagicMock()
    submission.url = url
    submission.stickied = False
    submission.is_self = False
    submission.score = 100
    submission.is_gallery = False
    submission.load = AsyncMock()
    for key, value in kwargs.items():
        setattr(submission, key, value)
    return submission


class TestRedditModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Reddit module."""

    async def asyncSetUp(self) -> None:
        """Copy the settings to a temporary folder."""
        SingletonMeta._instances.clear()
        self.temp_dir = tempfile.mkdtemp()
        self.settings_path = str(Path(self.temp_dir) / "settings.json")
        shutil.copy("tests/data/reddit_unit_test_settings.json", self.settings_path)

    async def asyncTearDown(self) -> None:
        """Remove the temporary folder."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        SingletonMeta._instances.clear()

    @staticmethod
    @contextmanager
    def mockRedditDependencies() -> Generator[AsyncMock]:
        """Mock dependencies for the Reddit module.

        Yields:
            AsyncMock: the mocked asyncpraw instance
        """
        with patch(
            "corgos_telegram_bot.modules.reddit.asyncpraw.Reddit",
            new_callable=Mock(),
        ) as mock_reddit:
            mock_reddit_instance = AsyncMock()
            mock_reddit.return_value = mock_reddit_instance

            yield mock_reddit_instance

    @staticmethod
    def mockSubreddit(mock_reddit: AsyncMock, submissions: list[MagicMock]) -> None:
        """Make the mocked reddit instance return the given submissions."""

        async def top(**_kwargs: Any) -> AsyncIterator[MagicMock]:
            for submission in submissions:
                await asyncio.sleep(0)
                yield submission

        subreddit = MagicMock()
        subreddit.top = top
        mock_reddit.subreddit = AsyncMock(return_value=subreddit)

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
        with self.assertRaises(EmptyQueueError):
            await reddit.getUrl()

    async def testScrapeGallery(self) -> None:
        """Test that only the images of a gallery are kept, with unescaped urls."""
        reddit = Reddit(settings_path=self.settings_path)
        media_metadata = {
            "a": {"m": "image/jpg", "s": {"u": "https://i.redd.it/a.jpg?w=1&amp;s=2"}},
            "b": {"m": "image/png", "s": {"u": "https://i.redd.it/b.png"}},
            "c": {"m": "image/gif", "s": {"u": "https://i.redd.it/c.gif"}},
            "d": {"m": "image/jpg"},
            "e": {"m": "image/jpg", "s": {}},
            "f": "not a dict",
        }

        urls = reddit._scrapeGallery(media_metadata)

        self.assertEqual(
            urls,
            ["https://i.redd.it/a.jpg?w=1&s=2", "https://i.redd.it/b.png"],
        )

    async def testScrapeImage(self) -> None:
        """Test that only urls pointing to images are kept."""
        reddit = Reddit(settings_path=self.settings_path)

        with patch.object(reddit, "_requestContentType", return_value="image/jpeg"):
            self.assertEqual(await reddit._scrapeImage("a.jpg"), "a.jpg")

        with patch.object(reddit, "_requestContentType", return_value="text/html"):
            self.assertIsNone(await reddit._scrapeImage("a.html"))

        with patch.object(
            reddit, "_requestContentType", side_effect=aiohttp.ClientError()
        ):
            self.assertIsNone(await reddit._scrapeImage("a.jpg"))

    async def testLoadPosts(self) -> None:
        """Test loading posts, skipping the invalid ones."""
        reddit = Reddit(settings_path=self.settings_path)
        submissions = [
            makeSubmission("https://i.redd.it/1.jpg"),
            makeSubmission("https://i.redd.it/2.jpg"),
            makeSubmission("https://i.redd.it/stickied.jpg", stickied=True),
            makeSubmission("https://i.redd.it/low.jpg", score=0),
            makeSubmission("https://v.redd.it/video"),
            makeSubmission(
                "https://reddit.com/gallery/1",
                is_gallery=True,
                media_metadata={
                    "a": {"m": "image/jpg", "s": {"u": "https://i.redd.it/3.jpg"}}
                },
            ),
        ]

        with self.mockRedditDependencies() as mock_reddit:
            self.mockSubreddit(mock_reddit, submissions)
            await reddit.start()
            with patch.object(reddit, "_requestContentType", return_value="image/jpeg"):
                loaded = await reddit.loadPostsAsync()
            await reddit.stop()

        self.assertEqual(loaded, 3)
        self.assertFalse(reddit.is_loading)
        urls = {await reddit.getUrl() for _ in range(3)}
        self.assertEqual(
            urls,
            {
                "https://i.redd.it/1.jpg",
                "https://i.redd.it/2.jpg",
                "https://i.redd.it/3.jpg",
            },
        )

    async def testLoadPostsWithFailingPost(self) -> None:
        """Test that a failing post does not prevent the others from loading."""
        reddit = Reddit(settings_path=self.settings_path)
        failing = makeSubmission("https://i.redd.it/fail.jpg")
        failing.load = AsyncMock(side_effect=RuntimeError("reddit is down"))
        submissions = [makeSubmission("https://i.redd.it/1.jpg"), failing]

        with self.mockRedditDependencies() as mock_reddit:
            self.mockSubreddit(mock_reddit, submissions)
            await reddit.start()
            with patch.object(reddit, "_requestContentType", return_value="image/jpeg"):
                loaded = await reddit.loadPostsAsync()
            await reddit.stop()

        self.assertEqual(loaded, 1)
        self.assertFalse(reddit.is_loading)

    async def testLoadPostsResetsLoadingOnError(self) -> None:
        """Test that the loading state is reset if reddit cannot be reached."""
        reddit = Reddit(settings_path=self.settings_path)

        with self.mockRedditDependencies() as mock_reddit:
            mock_reddit.subreddit = AsyncMock(side_effect=RuntimeError("down"))
            await reddit.start()
            with self.assertRaises(RuntimeError):
                await reddit.loadPostsAsync()
            await reddit.stop()

        self.assertFalse(reddit.is_loading)

    async def testGetUrlRotatesQueue(self) -> None:
        """Test that the queue is rotated when getting urls."""
        reddit = Reddit(settings_path=self.settings_path)
        for url in ("a", "b"):
            reddit._queue.put_nowait(url)

        self.assertEqual(
            [await reddit.getUrl() for _ in range(4)],
            ["a", "b", "a", "b"],
        )
