"""File containing the reddit interface to steal the images from reddit."""

import ujson
import logging
import asyncpraw

from random import randint, shuffle
from urllib.request import urlopen


class EmptyQueueException(Exception):
    """Exception raised when the queue is empty."""

    pass


class Reddit:
    """This class contains all the methods and variables needed to load the \
    urls of the pictures from reddit."""

    def __init__(self) -> None:
        """Initialize the Reddit interface."""
        # clean the queue
        self._queue = []
        self._settings = {}
        self._settings_path = "settings.json"
        # whenever we scrape a link, we want to be sure it's just an image
        # and not, for instance, a gif or a video. So this is a list of allowed
        # image formats
        self._image_formats = ("image/png", "image/jpeg")
        # load settings
        self._loadSettings()

    # Private methods

    def _loadSettings(self) -> None:
        """Load settings from the settings file.

        Unless differently specified during the instantiation, \
        the default settings path is used.
        """
        with open(self._settings_path) as json_file:
            # only keeps settings for Reddit, discarding others
            self._settings = ujson.load(json_file)["Reddit"]

    def _saveSettings(self) -> None:
        """Save settings in the settings file.

        Unless differently specified during the instantiation, \
        the default settings path is used.
        """
        with open(self._settings_path) as json_file:
            old_settings = ujson.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Reddit"].update(self._settings)

        with open(self._settings_path, "w") as outfile:
            ujson.dump(old_settings, outfile, indent=2)

    def _checkSingleImage(self, url: str) -> bool:
        """Check if a url is a valid image.

        Args:
            url (str): Reddit post url

        Returns:
            bool
        """
        try:
            # log the content type in order to make sure it's an image
            content_type = urlopen(url).info()["content-type"]
        except Exception as e:
            # if it fails, it's because the image has been removed
            logging.error(f"Cannot open url {url}, error {e}")
            return False

        # if it's not an image, we skip the current url
        if content_type not in self._image_formats:
            return False

        return True

    def _scrapeGallery(self, media_metadata: dict) -> list[str]:
        """Scrape a gallery of images.

        Args:
            url (str): url of the gallery
        """
        urls = []
        for media in media_metadata.items():
            urls.append(media[1]["s"]["u"])
        return urls

    # Public methods

    def login(self) -> None:
        """Log into reddit.

        User authentication details are loaded from settings file.
        """
        self._reddit = asyncpraw.Reddit(
            client_id=self._settings["client_id"],
            client_secret=self._settings["client_secret"],
            user_agent=self._settings["user_agent"],
        )

        logging.info("Logged into Reddit")

    async def loadPosts(self) -> int:
        """Load all image posts from the needed subreddit.

        The links are shuffled and kept into memory.

        Returns:
            int: number of loaded posts
        """
        # empties the queue
        new_queue = []

        subreddits = await self._reddit.subreddit("corgi+babycorgis")
        async for submission in subreddits.top(
            "week", limit=self._settings["post_limit"]
        ):

            # skip stickied and selftexts, we don't need those
            if submission.selftext or submission.stickied:
                continue

            # skip posts that have a low score
            if submission.score < self._settings["min_score"]:
                continue

            # filter gifs
            if "v.redd.it" in submission.url or ".gif" in submission.url:
                continue

            await submission.load()

            # try to open the image
            if hasattr(submission, "is_gallery"):
                scraped_urls = self._scrapeGallery(submission.media_metadata)
            else:
                scraped_urls = [submission.url]

            # check the url for each image
            for url in scraped_urls:
                # if it's a valid image, we add it to the queue
                if self._checkSingleImage(url):
                    new_queue.append(url)

        # shuffles the list to make it more random
        shuffle(new_queue)

        # copy the new queue to the old one
        self._queue = [url for url in new_queue]
        return len(self._queue)

    def getImage(self) -> str:
        """Return the url of the next image in the queue."""
        # if somehow we did not load anything, we throw an exception
        # this should likely never happen, but might be triggered if the queue
        # has not been loaded yet
        if len(self._queue) == 0:
            raise EmptyQueueException("Queue is empty.")

        url = self._queue[0]  # first in rotation is the next url
        self._queue.append(self._queue.pop(0))  # list rotation
        return url

    def removeImage(self, url: str) -> None:
        """Remove an url from the queue.

        Args:
            url (str): url to be removed
        """
        self._queue.remove(url)

    @property
    def queueSize(self) -> int:
        """Return the size of the queue."""
        return len(self._queue)
