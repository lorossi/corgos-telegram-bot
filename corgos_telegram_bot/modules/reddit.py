"""File containing the reddit interface to steal the images from reddit."""

import asyncio
import logging
import os
import shutil
from queue import Queue
from random import shuffle

import aiofiles
import aiohttp
import asyncpraw
from asyncpraw.models import Submission

from corgos_telegram_bot.modules.settings import Settings


class EmptyQueueException(Exception):
    """Exception raised when the queue is empty."""


class Reddit:
    """This class contains all the logic to load pictures from reddit."""

    _is_loading: bool
    _settings_path: str
    _image_formats: tuple[str, ...] = (
        "image/png",
        "image/jpeg",
        "image/jpg",
    )

    _temp_queue: list[str]
    _queue: Queue[str]

    _temp_queue_lock: asyncio.Lock
    _queue_lock: asyncio.Lock

    _praw_requests_semaphore: asyncio.Semaphore
    _http_requests_semaphore: asyncio.Semaphore
    _reddit: asyncpraw.Reddit
    _settings: Settings

    def __init__(self, settings_path: str = "settings.json") -> None:
        """Initialize the Reddit interface."""
        logging.info("Initializing Reddit interface")

        self._settings_path = settings_path
        self._is_loading = False

        self._queue = Queue()
        self._temp_queue = []

        self._temp_queue_lock = asyncio.Lock()
        self._queue_lock = asyncio.Lock()

        logging.info("Reddit interface initialized")

    def __del__(self) -> None:
        """Destructor to clean up resources."""

    # Private methods
    async def _createTempFolder(self) -> None:
        """Create the temporary folder for caching images."""
        logging.info("Creating temporary folder for caching images")
        cache_folder = await self._settings.get("reddit_cache_folder")
        shutil.rmtree(cache_folder, ignore_errors=True)
        os.makedirs(cache_folder, exist_ok=True)
        logging.info(f"Temporary folder {cache_folder} created")

    async def _deleteTempFolder(self) -> None:
        """Delete the temporary folder for caching images."""
        logging.info("Deleting temporary folder for caching images")
        cache_folder = await self._settings.get("reddit_cache_folder")
        shutil.rmtree(cache_folder, ignore_errors=True)
        logging.info(f"Temporary folder {cache_folder} deleted")

    async def _extractFilenameFromUrl(self, x: int, url: str) -> str:
        """Extract the filename from the specified url.

        Args:
            x (int): index of the image
            url (str): url to extract the filename from

        Returns:
            str: filename extracted from the url
        """
        logging.debug(f"Extracting filename from url {url}")
        folder = await self._settings.get("reddit_cache_folder")
        filename = url.split("/")[-1].split("?")[0]
        filepath = os.path.join(folder, f"{x}_{filename}")
        logging.debug(f"Filename extracted from url {url} is {filepath}")
        return filepath

    async def _downloadImage(self, url: str, filepath: str) -> None:
        """Download an image from the specified url to the specified filepath.

        Args:
            url (str): url of the image
            filepath (str): filepath to save the image

        """
        logging.debug(f"Downloading image from url {url} to filepath {filepath}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.headers["content-type"] not in self._image_formats:
                        logging.debug(f"Url {url} is not an image, skipping download")
                        return

                    async with aiofiles.open(filepath, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024):
                            await f.write(chunk)
        except Exception as e:
            logging.error(f"Cannot download image from url {url}, error {e}")

    async def _scrapeGallery(self, media_metadata: dict) -> list[str]:
        """Scrape a gallery of images.

        Args:
            media_metadata (dict): media metadata of the gallery


        Returns:
            list[str]: list of image urls
        """
        logging.debug("Scraping gallery")
        urls = []
        for media in media_metadata.items():
            if len(media) < 2:
                logging.debug("Media metadata is not valid, skipping")
                continue

            image_format = media[1].get("m", None)
            if image_format is None:
                logging.debug("Url is not an image, skipping")
                continue

            if image_format in self._image_formats:
                logging.debug("Url is an image, adding to queue")
                continue

            image_obj = media[1].get("s", None)
            if image_obj is None:
                logging.debug("Url gallery does not contain this image, skipping")
                continue

            image_url = media[1]["s"].get("u", None)
            if image_url is None:
                logging.debug("Url is not an image, skipping")
                continue

            urls.append(image_url)

        logging.debug(f"Found {len(urls)} images in gallery")
        return urls

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
            logging.debug(f"Loading post with url {submission.url}")  # type: ignore
            # skip stickied posts
            if submission.stickied:  # type: ignore
                logging.debug(f"Skipping post {submission.url} due to stickied")  # type: ignore
                return False
            # skip selftext posts
            if submission.is_self:  # type: ignore
                logging.debug(f"Skipping post {submission.url} due to selftext")  # type: ignore
                return False

            # skip posts that have a low score
            if submission.score < min_score:  # type: ignore
                logging.warning(
                    f"Skipping post {submission.url} due to low score "  # type: ignore
                    f"({submission.score}, min {min_score})"  # type: ignore
                )
                return False

            # filter reddit video
            if "v.redd.it" in submission.url:  # type: ignore
                logging.warning(f"Skipping post {submission.url} because is gif")  # type: ignore
                return False

            logging.debug("Post passed all checks, loading")

            # try to open the image
            urls = []
            if hasattr(submission, "is_gallery"):
                logging.debug("Post is a gallery, scraping")
                urls = await self._scrapeGallery(submission.media_metadata)  # type: ignore
            else:
                logging.debug("Post is not a gallery, scraping")
                urls = [submission.url]  # type: ignore

            for x, url in enumerate(urls):
                logging.debug("Downloading image %d/%d from post", x + 1, len(urls))
                filepath = await self._extractFilenameFromUrl(x, url)
                await self._downloadImage(url, filepath)
                async with self._temp_queue_lock:
                    self._temp_queue.append(filepath)

            return True

    async def _openReddit(self) -> None:
        """Log in to Reddit using asyncpraw."""
        logging.info("Logging into Reddit")
        self._reddit = asyncpraw.Reddit(
            client_id=await self._settings.get("reddit_client_id"),
            client_secret=await self._settings.get("reddit_client_secret"),
            user_agent=await self._settings.get("reddit_user_agent"),
        )
        logging.info("Logged into Reddit")

    async def _closeReddit(self) -> None:
        """Log out from Reddit."""
        logging.info("Logging out from Reddit")
        await self._reddit.close()
        logging.info("Logged out from Reddit")

    # Public methods
    async def start(self) -> None:
        """Start the Reddit interface."""
        logging.info("Starting Reddit interface")
        # load settings
        logging.debug("Loading settings")
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
                "reddit_cache_folder",
            ]
        )
        logging.debug("Settings loaded and validated")

        # create temp folder
        await self._createTempFolder()

        # create a semaphore for the reddit requests
        self._praw_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_praw_concurrent_requests")
        )
        # create a semaphore for the http requests
        self._http_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_http_concurrent_requests")
        )

        await self._openReddit()

        logging.debug("Reddit interface started")

    async def stop(self) -> None:
        """Stop the Reddit interface."""
        logging.info("Stopping Reddit interface")
        await self._deleteTempFolder()
        await self._closeReddit()
        logging.info("Reddit interface stopped")

    async def loadPostsAsync(self) -> int:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of posts loaded
        """
        logging.info("Loading posts from Reddit")
        self._is_loading = True
        async with self._temp_queue_lock:
            self._temp_queue = []

        # load subreddits
        subreddits_list = await self._settings.get("reddit_subreddits")
        subreddits = await self._reddit.subreddit("+".join(subreddits_list))  # type: ignore
        # create a list of tasks to be executed
        logging.debug("Creating tasks")
        min_score = await self._settings.get("reddit_min_score")
        posts_limit = await self._settings.get("reddit_posts_limit")
        tasks = {
            self._scrapePost(submission, min_score=min_score)
            async for submission in subreddits.top(
                time_filter="week", limit=posts_limit
            )
        }
        logging.debug("Executing tasks")
        # execute all the tasks and wait for them to finish
        await asyncio.gather(*tasks)

        logging.debug("Shuffling loaded posts")
        await self._temp_queue_lock.acquire()
        shuffle(self._temp_queue)

        await self._queue_lock.acquire()
        for filepath in self._temp_queue:
            self._queue.put(filepath)
        self._queue_lock.release()
        self._temp_queue_lock.release()

        self._is_loading = False

        # return the number of posts loaded
        logging.info("Loaded about %d posts from Reddit", len(self._temp_queue))
        return len(self._temp_queue)

    async def getPhoto(self) -> str:
        """Get an image from the queue.

        Returns:
            str: filepath of the image

        Raises:
            EmptyQueueException: if the queue is empty
        """
        async with self._queue_lock:
            if self._queue.empty():
                logging.warning("Reddit queue is empty")
                raise EmptyQueueException("Reddit queue is empty")
            # rotate the queue
            filepath = self._queue.get()
            self._queue.put(filepath)

        return filepath

    async def isQueueEmpty(self) -> bool:
        """Check if the queue is empty.

        Returns:
            bool: True if the queue is empty, False otherwise
        """
        async with self._queue_lock:
            is_empty = self._queue.empty()
        return is_empty

    @property
    def is_loading(self) -> bool:
        """Check if the Reddit interface is loading posts.

        Returns:
            bool: True if loading, False otherwise
        """
        return self._is_loading
