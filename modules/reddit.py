import os
import praw
import ujson
import logging

from random import shuffle
from urllib.request import urlopen


package_directory = os.path.dirname(os.path.abspath(__file__))


class Reddit:
    """
    This class contains all the methods and variables needed to load the
    urls of the pictures from reddit
    """

    def __init__(self):
        """
        initializes the Reddit handler
        """
        # clean the queue
        self._queue = []
        self._settings = {}
        self._settings_path = package_directory + "/settings.json"
        # whenever we scrape a link, we want to be sure it's just an image
        # and not, for instance, a gif or a video. So this is a list of allowed
        # image formats
        self.image_formats = ("image/png", "image/jpeg")
        # load settings
        self._loadSettings()

    # Private methods

    def _loadSettings(self):
        """
        loads settings from the settings file.
        unless specified, we use the default settings path
        """

        with open(self._settings_path) as json_file:
            # only keeps settings for Reddit, discarding others
            self._settings = ujson.load(json_file)["Reddit"]

    def _saveSettings(self):
        """
        saves settings into file
        """

        with open(self._settings_path) as json_file:
            old_settings = ujson.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Reddit"].update(self._settings)

        with open(self._settings_path, 'w') as outfile:
            ujson.dump(old_settings, outfile, indent=2)

    # Public methods

    def login(self):
        """
        logs in Reddit
        """

        self.reddit = praw.Reddit(
            client_id=self._settings["client_id"],
            client_secret=self._settings["client_secret"],
            user_agent=self._settings["user_agent"]
        )

        logging.info("Logged into Reddit")

    def loadPosts(self):
        """
        loads all posts and returns the number of scraped urls
        """

        subreddit = self.reddit.subreddit('corgi+babycorgis')
        submissions = subreddit.top('week', limit=self._settings["post_limit"])
        # empties the queue
        self._queue = []

        for s in submissions:

            # skips stickied and selftexts, we don't need those
            if s.selftext or s.stickied:
                continue

            # skips posts that have a low score
            if s.score < self._settings["min_score"]:
                continue

            # filters gifs
            if "v.redd.it" in s.url or ".gif" in s.url:
                continue

            # try to open the image
            try:
                # log the content type in order to make sure it's an image
                content_type = urlopen(s.url).info()["content-type"]
            except Exception as e:
                # if it fails, it's because the image has been removed
                logging.error(f"Cannot open url {s.url}, error {e}")
                continue

            # if it's not an image, we skip the current url
            if content_type not in self.image_formats:
                continue

            # appends to queue list
            self._queue.append(s.url)

        # shuffles the list to make it more random
        shuffle(self._queue)
        return len(self._queue)

    def getImage(self):
        """
        returns the url of a photo
        """

        # if somehow we did not load anything, we reload some posts
        # this should likely never happen, but might be triggered if the queue
        # has not been loaded yet
        if len(self._queue) == 0:
            self.loadPosts()

        url = self._queue[0]  # first in rotation is the next url
        self._queue.append(self._queue.pop(0))  # list rotation
        return url

    def removeImage(self, url):
        self._queue.remove(url)
        return

    # Setters and getter
