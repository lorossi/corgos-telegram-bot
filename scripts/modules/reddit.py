"""File containing the reddit interface to steal the images from reddit."""

import asyncio
import logging
from queue import Queue
from random import shuffle

import aiohttp
import asyncpraw
from asyncpraw.models import Submission

from modules.settings import Settings


class EmptyQueueException(Exception):
    """Exception raised when the queue is empty."""


class Reddit:
    """This class contains all the methods and variables needed to load the urls of the pictures from reddit."""

    _queue: Queue[str]
    _temp_queue: set[str]
    _queue_lock: asyncio.Lock
    _temp_queue_lock: asyncio.Lock
    _praw_requests_semaphore: asyncio.Semaphore
    _http_requests_semaphore: asyncio.Semaphore
    _reddit: asyncpraw.Reddit
    _is_loading: bool = False

    _settings: dict[str, str | int]
    _settings_path: str = "settings.json"
    _image_formats: tuple[str] = ("image/png", "image/jpeg")

    def __init__(self) -> None:
        """Initialize the Reddit interface."""
        logging.info("Initializing Reddit interface")
        # create the queues
        self._queue = Queue()
        self._temp_queue = set()
        # create a lock for the new queue
        self._queue_lock = asyncio.Lock()
        self._temp_queue_lock = asyncio.Lock()
        logging.info("Reddit interface initialized")

    # Private methods

    async def _asyncRequest(self, url: str) -> aiohttp.ClientResponse:
        """Make an async request to the specified url.

        Args:
            url (str): url to be requested

        Returns:
            Response: response of the request
        """
        async with self._http_requests_semaphore:
            logging.debug(f"Requesting url {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    logging.debug(f"Request to url {url} completed")
                    return response

    async def _scrapeGallery(self, media_metadata: dict) -> list[str]:
        """Scrape a gallery of images.

        Args:
            url (str): url of the gallery
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

            image_valid = await self._scrapeImage(image_url)
            if image_valid is None:
                logging.debug("Url is not an image, skipping")
                continue

            urls.append(image_url)

        logging.debug(f"Found {len(urls)} images in gallery")
        return urls

    async def _scrapeImage(self, url: str) -> str:
        """Load a single image, check if it's valid and add it to the queue.

        Args:
            url (str): url of the image
        """
        logging.debug(f"Checking url {url}")
        try:
            r = await self._asyncRequest(url)
            image_format = r.headers["content-type"]
            if image_format in self._image_formats:
                logging.debug("Url is an image, adding to queue")
                return url
            else:
                logging.debug(f"Url is not an image, skipping. Format: {image_format}")
                return None
        except Exception as e:
            logging.error(f"Cannot open url {url}, error {e}")
            return None

    async def _scrapePost(
        self,
        submission: Submission,
        min_score: int = 5,
    ) -> bool:
        """Scrape a post from Reddit and add it to the temporary queue.

        Args:
            submission (Submission)

        Returns:
            bool: True if the post is valid, False otherwise
        """
        async with self._praw_requests_semaphore:
            logging.info(f"Loading post with url {submission.url}")
            # skip stickied posts
            if submission.stickied:
                logging.warning(f"Skipping post {submission.url} due to stickied")
                return False
            # skip selftext posts
            if submission.is_self:
                logging.warning(f"Skipping post {submission.url} due to selftext")
                return False

            # skip posts that have a low score
            if submission.score < min_score:
                logging.warning(
                    f"Skipping post {submission.url} due to low score "
                    f"({submission.score}, min {min_score})"
                )
                return False

            # filter gifs
            if any(x in submission.url for x in [".gif", ".gifv", "v.redd.it"]):
                logging.warning(f"Skipping post {submission.url} because is gif")
                return False

            logging.debug("Post passed all checks, loading")
            await submission.load()

            # try to open the image
            scraped_urls = []
            if hasattr(submission, "is_gallery"):
                logging.debug("Post is a gallery, scraping")
                scraped_urls = await self._scrapeGallery(submission.media_metadata)
            else:
                logging.debug("Post is not a gallery, scraping")
                new_url = await self._scrapeImage(submission.url)
                scraped_urls.append(new_url)

            # check the url for each image
            for url in scraped_urls:
                # if it's a valid image, we add it to the queue
                logging.debug(f"Adding {url} to list")
                async with self._temp_queue_lock:
                    self._temp_queue.add(url)
                logging.info(f"Added {url} to list")

            return True

    # Public methods
    async def start(self) -> None:
        """Start the Reddit interface."""
        logging.info("Starting Reddit interface")
        # load settings
        self._settings = Settings(self._settings_path)
        await self._settings.load()

        # create a semaphore for the reddit requests
        self._praw_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_praw_concurrent_requests")
        )
        # create a semaphore for the http requests
        self._http_requests_semaphore = asyncio.Semaphore(
            await self._settings.get("reddit_http_concurrent_requests")
        )

        logging.info("Logging into Reddit")

        self._reddit = asyncpraw.Reddit(
            client_id=await self._settings.get("reddit_client_id"),
            client_secret=await self._settings.get("reddit_client_secret"),
            user_agent=await self._settings.get("reddit_user_agent"),
        )

        logging.debug("Reddit interface started")

    async def stop(self) -> None:
        """Stop the Reddit interface."""
        logging.info("Stopping Reddit interface")
        await self._reddit.close()
        logging.info("Reddit interface stopped")

    async def loadPostsAsync(self) -> None:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of posts loaded
        """
        logging.info("Loading posts from Reddit")
        # empty the queue
        async with self._temp_queue_lock:
            self._temp_queue = set()
            self._is_loading = True

        # load subreddits
        subreddits = await self._reddit.subreddit("corgi+babycorgis")
        # create a list of tasks to be executed
        logging.debug("Creating tasks")
        min_score = await self._settings.get("reddit_min_score")
        posts_limit = await self._settings.get("reddit_posts_limit")
        tasks = {
            self._scrapePost(submission, min_score=min_score)
            async for submission in subreddits.top("week", limit=posts_limit)
        }
        logging.debug("Executing tasks")
        # execute all the tasks and wait for them to finish
        await asyncio.gather(*tasks)

        # shuffle the queue and empty the temporary queue
        await self._queue_lock.acquire()
        await self._temp_queue_lock.acquire()

        shuffled_queue = list(self._temp_queue)
        shuffle(shuffled_queue)

        self._queue = Queue(len(self._temp_queue))
        for url in shuffled_queue:
            self._queue.put(url)

        self._is_loading = False

        self._temp_queue_lock.release()
        self._queue_lock.release()

        # return the number of posts loaded
        logging.info("Loaded about %d posts from Reddit", self._queue.qsize())
        return self._queue.qsize()

    async def getUrl(self) -> str:
        """Return the url of the next image in the queue."""
        # if somehow we did not load anything, we throw an exception
        # this should likely never happen, but might be triggered if the queue
        # has not been loaded yet
        logging.info("Getting next image from queue")
        queue_size = await self.getQueueSize()
        if queue_size == 0:
            error_msg = "Queue is empty"
            logging.error(error_msg)
            raise EmptyQueueException(error_msg)

        url = await self._rotateQueue()
        logging.info(f"Next image is %s", url)
        return url

    async def removeUrl(self, url: str) -> None:
        """Remove an url from the queue.

        Args:
            url (str): url to be removed
        """
        logging.debug("Removing url %s from queue", url)
        async with self._queue_lock:
            temp_queue = Queue(len(self._queue))
            while not self._queue.empty():
                current_url = self._queue.get()
                if current_url != url:
                    temp_queue.put(current_url)
            self._queue = temp_queue

    async def _rotateQueue(self) -> str:
        """Rotate the queue and return the next url.

        Returns:
            str: next url
        """
        logging.debug("Rotating queue")

        async with self._queue_lock:
            url = self._queue.get()
            self._queue.put(url)

        logging.debug(f"Next url is %s", url)
        return url

    async def getTempQueueSize(self) -> int:
        """Return the size of the temporary queue."""
        logging.debug("Getting temporary queue size")
        await self._temp_queue_lock.acquire()
        size = len(self._temp_queue)
        self._temp_queue_lock.release()

        logging.debug("Temporary queue size is %d", size)
        return size

    async def getQueueSize(self) -> int:
        """Return the size of the queue."""
        logging.debug("Getting queue size")
        async with self._queue_lock:
            size = self._queue.qsize()

        logging.debug(f"Queue size is %d", size)
        return size

    @property
    def is_loading(self) -> bool:
        """Return True if the queue is being loaded, False otherwise."""
        return self._is_loading
