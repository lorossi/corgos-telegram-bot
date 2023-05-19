"""File containing the reddit interface to steal the images from reddit."""

import asyncio
import logging
from random import shuffle

import asyncpraw
import requests
import ujson
from asyncpraw.models import Submission


class EmptyQueueException(Exception):
    """Exception raised when the queue is empty."""

    pass


class Reddit:
    """This class contains all the methods and variables needed to load the \
    urls of the pictures from reddit."""

    _queue: list[str]
    _new_queue: list[str]
    _settings: dict
    _settings_path: str = "settings.json"
    _image_formats: tuple[str] = ("image/png", "image/jpeg")

    def __init__(self) -> None:
        """Initialize the Reddit interface."""
        logging.info("Initializing Reddit interface")
        # clean the queue
        self._queue = []
        self._settings = {}
        # load settings
        self._loadSettings()
        logging.info("Reddit interface initialized")

    # Private methods

    def _loadSettings(self) -> None:
        """Load settings from the settings file.

        Unless differently specified during the instantiation, \
        the default settings path is used.
        """
        logging.debug("Loading settings")
        with open(self._settings_path) as json_file:
            # only keeps settings for Reddit, discarding others
            self._settings = ujson.load(json_file)["Reddit"]
        logging.debug("Settings loaded")

    def _saveSettings(self) -> None:
        """Save settings in the settings file.

        Unless differently specified during the instantiation, \
        the default settings path is used.
        """
        logging.debug("Saving settings")
        with open(self._settings_path) as json_file:
            old_settings = ujson.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Reddit"].update(self._settings)

        with open(self._settings_path, "w") as outfile:
            ujson.dump(old_settings, outfile, indent=2)
        logging.debug("Settings saved")

    def _scrapeGallery(self, media_metadata: dict) -> list[str]:
        """Scrape a gallery of images.

        Args:
            url (str): url of the gallery
        """
        logging.debug("Scraping gallery")
        urls = []
        for media in media_metadata.items():
            image_format = media[1]["m"]

            if image_format in self._image_formats:
                continue

            image_url = media[1]["s"].get("u", None)
            if image_url is None:
                continue

            urls.append(image_url)

        logging.debug(f"Found {len(urls)} images in gallery")
        return urls

    def _scrapeImage(self, url: str) -> list[str]:
        """Scrape a single image.

        Args:
            url (str): url of the image
        """
        logging.debug(f"Checking url {url}")
        try:
            r = requests.head(url)
            image_format = r.headers["content-type"]
            if image_format in self._image_formats:
                logging.debug("Url is an image, adding to queue")
                return [url]
            else:
                logging.debug(f"Url is not an image, skipping. Format: {image_format}")
                return []
        except Exception as e:
            logging.error(f"Cannot open url {url}, error {e}")
            return []

    # Public methods

    def login(self) -> None:
        """Log into reddit.

        User authentication details are loaded from settings file.
        """
        logging.info("Logging into Reddit")

        self._reddit = asyncpraw.Reddit(
            client_id=self._settings["client_id"],
            client_secret=self._settings["client_secret"],
            user_agent=self._settings["user_agent"],
        )

        logging.debug("Logged into Reddit")

    async def _scrapePost(
        self,
        submission: Submission,
        semaphore: asyncio.Semaphore,
        queue_lock: asyncio.Lock,
    ) -> bool:
        async with semaphore:
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
            if submission.score < self._settings["min_score"]:
                logging.warning(
                    f"Skipping post {submission.url} due to low score "
                    f"({submission.score}, min {self._settings['min_score']})"
                )
                return False

            # filter gifs
            if any(x in submission.url for x in [".gif", ".gifv", "v.redd.it"]):
                logging.warning(f"Skipping post {submission.url} because is gif")
                return False

            logging.debug("Post passed all checks, loading")
            await submission.load()

            # try to open the image
            if hasattr(submission, "is_gallery"):
                logging.debug("Post is a gallery, scraping")
                scraped_urls = self._scrapeGallery(submission.media_metadata)
            else:
                logging.debug("Post is not a gallery, scraping")
                scraped_urls = self._scrapeImage(submission.url)

            # check the url for each image
            for url in scraped_urls:
                logging.debug(f"Adding {url} to list")
                # if it's a valid image, we add it to the queue
                await queue_lock.acquire()
                self._new_queue.append(url)
                queue_lock.release()
                logging.info(f"Added {url} to list")

    async def loadPostsAsync(self) -> int:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of loaded posts
        """
        logging.info("Loading posts from Reddit")
        # empties the queue
        self._new_queue = []

        # create a semaphore to limit the number of concurrent requests
        semaphore = asyncio.Semaphore(self._settings["concurrent_requests"])
        # create a lock for the new queue
        lock = asyncio.Lock()
        # load subreddits
        subreddits = await self._reddit.subreddit("corgi+babycorgis")
        # create a list of tasks to be executed
        logging.debug("Creating tasks")
        tasks = {
            self._scrapePost(submission, semaphore, lock)
            async for submission in subreddits.top(
                "week", limit=self._settings["post_limit"]
            )
        }

        logging.debug("Executing tasks")
        try:
            # execute the tasks
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logging.error("Posta loading cancelled")
            return 0

        # shuffle the list to make it more random
        shuffle(self._new_queue)

        # copy the new queue to the old one
        self._queue = self._new_queue.copy()
        logging.info(f"Loaded {len(self._queue)} posts from Reddit")
        return len(self._queue)

    def loadPosts(self) -> int:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of loaded posts
        """
        return asyncio.run(self.loadPostsAsync())

    def getImage(self) -> str:
        """Return the url of the next image in the queue."""
        # if somehow we did not load anything, we throw an exception
        # this should likely never happen, but might be triggered if the queue
        # has not been loaded yet
        logging.info("Getting next image from queue")
        if len(self._queue) == 0:
            raise EmptyQueueException("Queue is empty.")

        url = self._queue[0]  # first in rotation is the next url
        self._queue.append(self._queue.pop(0))  # list rotation
        logging.info(f"Next image is {url}")
        return url

    def removeImage(self, url: str) -> None:
        """Remove an url from the queue.

        Args:
            url (str): url to be removed
        """
        logging.debug(f"Removing url {url} from queue")
        self._queue.remove(url)

    @property
    def queueSize(self) -> int:
        """Return the size of the queue."""
        return len(self._queue)
