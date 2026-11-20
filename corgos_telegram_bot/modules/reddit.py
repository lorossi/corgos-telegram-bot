"""File containing the reddit interface to steal the images from reddit."""

import asyncio
import html
import logging
from asyncio import Queue, QueueEmpty
from http import HTTPStatus
from random import shuffle
from typing import Any

import aiohttp
import asyncpraw
from asyncpraw.models import Submission

from corgos_telegram_bot.modules.settings import Settings

logger = logging.getLogger(__name__)


class EmptyQueueError(Exception):
    """Exception raised when the queue is empty."""


class Reddit:
    """This class contains all the logic to load pictures from reddit."""

    _queue: Queue[str]
    _temp_queue: set[str]
    _queue_lock: asyncio.Lock
    _temp_queue_lock: asyncio.Lock
    _praw_requests_semaphore: asyncio.Semaphore
    _http_requests_semaphore: asyncio.Semaphore
    _http_session: aiohttp.ClientSession
    _reddit: asyncpraw.Reddit
    _is_loading: bool

    _settings: Settings
    _settings_path: str
    _image_formats: tuple[str, ...] = ("image/png", "image/jpeg", "image/jpg")
    _http_timeout: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=15)

    def __init__(self, settings_path: str = "settings.json") -> None:
        """Initialize the Reddit interface."""
        logger.info("Initializing Reddit interface")
        self._settings_path = settings_path
        # create the queues
        self._queue = Queue()
        self._temp_queue = set()
        # create a lock for the new queue
        self._queue_lock = asyncio.Lock()
        self._temp_queue_lock = asyncio.Lock()
        # Initialize loading state
        self._is_loading = False
        logger.info("Reddit interface initialized")

    # Private methods

    async def _requestContentType(self, url: str) -> str | None:
        """Request the content type of the specified url.

        A HEAD request is tried first so the image itself is not downloaded;
        servers that do not support it are queried with a GET request.

        Args:
            url (str): url to be requested

        Returns:
            str | None: content type of the url, None if the request failed
        """
        async with self._http_requests_semaphore:
            logger.debug("Requesting url %s", url)
            async with self._http_session.head(url, allow_redirects=True) as response:
                status = response.status
                content_type = response.headers.get("content-type")

            if status == HTTPStatus.METHOD_NOT_ALLOWED:
                logger.debug("HEAD not allowed for url %s, using GET", url)
                async with self._http_session.get(url) as response:
                    status = response.status
                    content_type = response.headers.get("content-type")

        logger.debug("Request to url %s completed with status %d", url, status)
        if status >= HTTPStatus.BAD_REQUEST or content_type is None:
            return None
        return content_type.split(";")[0].strip().lower()

    def _scrapeGallery(self, media_metadata: dict[str, Any]) -> list[str]:
        """Scrape a gallery of images.

        Args:
            media_metadata (dict[str, Any]): media metadata of the gallery

        Returns:
            list[str]: list of image urls
        """
        logger.debug("Scraping gallery")
        urls = []
        for media in media_metadata.values():
            if not isinstance(media, dict):
                logger.debug("Media metadata is not valid, skipping")
                continue

            image_format = media.get("m")
            if image_format not in self._image_formats:
                logger.debug("Gallery item is not an image, skipping")
                continue

            image_obj = media.get("s")
            if not isinstance(image_obj, dict):
                logger.debug("Gallery does not contain this image, skipping")
                continue

            image_url = image_obj.get("u")
            if image_url is None:
                logger.debug("Gallery item has no url, skipping")
                continue

            # reddit escapes the urls in the gallery metadata (& -> &amp;)
            urls.append(html.unescape(image_url))

        logger.debug("Found %d images in gallery", len(urls))
        return urls

    async def _scrapeImage(self, url: str) -> str | None:
        """Load a single image and check if it's valid.

        Args:
            url (str): url of the image

        Returns:
            str | None: url of the image if valid, None otherwise
        """
        logger.debug("Checking url %s", url)
        try:
            image_format = await self._requestContentType(url)
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("Cannot open url %s, error %s", url, e)
            return None

        if image_format in self._image_formats:
            logger.debug("Url is an image, adding to queue")
            return url

        logger.debug("Url is not an image, skipping. Format: %s", image_format)
        return None

    async def _scrapePost(
        self,
        submission: Submission,
        min_score: int = 5,
    ) -> bool:
        """Scrape a post from Reddit and add it to the temporary queue.

        Args:
            submission (Submission): submission to be scraped
            min_score (int): minimum score for the post to be valid. Defaults to 5.

        Returns:
            bool: True if the post is valid, False otherwise
        """
        async with self._praw_requests_semaphore:
            logger.debug("Loading post with url %s", submission.url)
            # skip stickied posts
            if submission.stickied:
                logger.debug("Skipping post %s due to stickied", submission.url)
                return False
            # skip selftext posts
            if submission.is_self:
                logger.debug("Skipping post %s due to selftext", submission.url)
                return False

            # skip posts that have a low score
            if submission.score < min_score:
                logger.debug(
                    "Skipping post %s due to low score (%d < %d)",
                    submission.url,
                    submission.score,
                    min_score,
                )
                return False

            # filter videos
            if "v.redd.it" in submission.url:
                logger.debug("Skipping post %s because is video", submission.url)
                return False

            logger.debug("Post passed all checks, loading")
            await submission.load()

            # try to open the image
            if getattr(submission, "is_gallery", False):
                logger.debug("Post is a gallery, scraping")
                urls = self._scrapeGallery(getattr(submission, "media_metadata", {}))
            else:
                logger.debug("Post is not a gallery, scraping")
                new_url = await self._scrapeImage(submission.url)
                if new_url is None:
                    logger.debug("Url is not an image, skipping")
                    return False

                urls = [new_url]

            # add each valid image to the queue
            async with self._temp_queue_lock:
                self._temp_queue.update(urls)
            logger.debug("Added %d urls to list", len(urls))

            return len(urls) > 0

    async def _openReddit(self) -> None:
        """Log in to Reddit using asyncpraw."""
        logger.info("Logging into Reddit")
        self._reddit = asyncpraw.Reddit(
            client_id=await self._settings.get("reddit_client_id"),
            client_secret=await self._settings.get("reddit_client_secret"),
            user_agent=await self._settings.get("reddit_user_agent"),
        )
        logger.info("Logged into Reddit")

    async def _closeReddit(self) -> None:
        """Log out from Reddit."""
        logger.info("Logging out from Reddit")
        await self._reddit.close()
        logger.info("Logged out from Reddit")

    # Public methods
    async def start(self) -> None:
        """Start the Reddit interface."""
        logger.info("Starting Reddit interface")
        # load settings
        logger.debug("Loading settings")
        self._settings = Settings(settings_path=self._settings_path)
        await self._settings.load()
        # validate settings
        await self._settings.validate(
            [
                "reddit_client_id",
                "reddit_client_secret",
                "reddit_user_agent",
                "reddit_subreddits",
                "reddit_min_score",
                "reddit_posts_limit",
                "reddit_praw_concurrent_requests",
                "reddit_http_concurrent_requests",
            ]
        )
        logger.debug("Settings loaded and validated")

        # create a semaphore for the reddit requests
        self._praw_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_praw_concurrent_requests")
        )
        # create a semaphore for the http requests
        self._http_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_http_concurrent_requests")
        )
        # create a single http session, shared by all the requests
        self._http_session = aiohttp.ClientSession(timeout=self._http_timeout)

        await self._openReddit()

        logger.debug("Reddit interface started")

    async def stop(self) -> None:
        """Stop the Reddit interface."""
        logger.info("Stopping Reddit interface")
        await self._closeReddit()
        await self._http_session.close()
        logger.info("Reddit interface stopped")

    async def loadPostsAsync(self) -> int:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of posts loaded
        """
        logger.info("Loading posts from Reddit")
        # empty the queue
        async with self._temp_queue_lock:
            self._temp_queue = set()
            self._is_loading = True

        try:
            await self._loadPostsInTempQueue()

            # shuffle the queue and empty the temporary queue
            async with self._queue_lock, self._temp_queue_lock:
                shuffled_queue = list(self._temp_queue)
                shuffle(shuffled_queue)

                self._queue = Queue(len(shuffled_queue))
                for url in shuffled_queue:
                    self._queue.put_nowait(url)
        finally:
            self._is_loading = False

        # return the number of posts loaded
        logger.info("Loaded %d posts from Reddit", len(shuffled_queue))
        return len(shuffled_queue)

    async def _loadPostsInTempQueue(self) -> None:
        """Scrape the top posts of the week and put them in the temporary queue."""
        # load settings
        subreddits_list = await self._settings.get("reddit_subreddits")
        subreddits = await self._reddit.subreddit("+".join(subreddits_list))
        posts_limit = await self._settings.get("reddit_posts_limit")
        min_score = await self._settings.get("reddit_min_score")
        # create a list of tasks to be executed
        logger.debug("Creating %d tasks", posts_limit)
        tasks = [
            self._scrapePost(submission, min_score=min_score)
            async for submission in subreddits.top(
                time_filter="week",
                limit=posts_limit,
            )
        ]
        logger.debug("Executing tasks")
        # execute all the tasks and wait for them to finish. A single failing
        #   post must not stop the others from being loaded
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Error while scraping post: %r", result)

    async def getUrl(self) -> str:
        """Return the url of the next image in the queue.

        Returns:
            str: url of the next image

        Raises:
            EmptyQueueError: if the queue is empty
        """
        logger.info("Getting next image from queue")
        async with self._queue_lock:
            try:
                url = self._queue.get_nowait()
            except QueueEmpty as e:
                error_msg = "Queue is empty"
                logger.warning(error_msg)
                raise EmptyQueueError(error_msg) from e
            # rotate the queue
            self._queue.put_nowait(url)

        logger.info("Next image is %s", url)
        return url

    async def isQueueEmpty(self) -> bool:
        """Return True if the queue is empty, False otherwise."""
        logger.debug("Checking if queue is empty")
        async with self._queue_lock:
            empty = self._queue.empty()

        logger.debug("Queue is empty: %s", empty)
        return empty

    @property
    def is_loading(self) -> bool:
        """Whether the queue is being loaded."""
        return self._is_loading
