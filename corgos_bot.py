# Corgos BOT, a fully functional Telegram image bot where all the photos
#   are stolen from Reddit.
# Contact him on telegram @corgos_bot (direct url: t.me/corgos_bot)
# This bot DOES NOT LOG every chat and user. As such, it cannot
#   (and it never will) send private message to the users or groups.
# Made by Lorenzo Rossi, 2019. Grazie a Giorgia per l'idea.
# This code is surprisingly fully PEP8 compliant.
# Yeah, I'm about as surprised as you.
# License: Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)

import os
import sys
import praw
import json
import random
import logging
from urllib.request import urlopen
from datetime import datetime, time
from telegram import ParseMode, ChatAction
from telegram.ext import Updater, CommandHandler, JobQueue, CallbackContext, \
                            MessageHandler, Filters


class Reddit:
    # This class contains all the methods and variables needed to load the
    # urls of the pictures from reddit

    def __init__(self):
        # intializes the queue to be empty at startup
        self.queue = []

    # loads settings from the settings file.
    def loadSettings(self, path="settings.json"):
        # unless specified, we use the default setting spath
        self.settings_path = path
        with open(self.settings_path) as json_file:
            # only keeps settings for Reddit, discarding others
            self.settings = json.load(json_file)["Reddit"]

        # save settings inside variables for easier access
        self.client_id = self.settings["client_id"]
        self.client_secret = self.settings["client_secret"]
        self.user_agent = self.settings["user_agent"]
        self.post_limit = self.settings["post_limit"]
        self.min_score = self.settings["min_score"]
        self.golden_corgos_found = self.settings["golden_corgos_found"]
        self.golden_corgo_url = self.settings["golden_corgo_url"]

        # whenever we scrape a link, we want to be sure it's just an image
        # and not, for instance, a gif or a video. So this is a list of allowed
        # image formats
        self.image_formats = ("image/png", "image/jpeg")

    # saves settings into file
    def saveSettings(self):
        with open(self.settings_path) as json_file:
                old_settings = json.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Reddit"].update(self.settings)

        with open(self.settings_path, 'w') as outfile:
            json.dump(old_settings, outfile, indent=4)

    # returns some meaningful informations needed in callbacks
    def showStatus(self):
        return {
            "golden_corgos_found": self.golden_corgos_found
        }

    #  Logs in reddit and return the reddit object
    def login(self):
        self.reddit = praw.Reddit(client_id=self.client_id,
                                  client_secret=self.client_secret,
                                  user_agent=self.user_agent)

        logging.info("Logged into Reddit")

    # loads all posts and returns the number of scraped urls
    def loadPosts(self):
        subreddit = self.reddit.subreddit('corgi+babycorgis')
        submissions = subreddit.top('week', limit=self.post_limit)
        # empties the queue
        self.queue = []

        for s in submissions:

            # skips sticked and selftexts, we don't need those
            if s.selftext or s.stickied:
                continue

            # skips posts that have a low score
            if s.score < self.min_score:
                continue

            # filters gifs
            if "v.redd.it" in s.url or ".gif" in s.url:
                continue

            # try to open the image
            try:
                # log the content type in order to make sure it's an image
                content_type = urlopen(s.url).info()["content-type"]
            except:
                # if it fails, it's beacuse the image has been removed
                logging.error("Cannot open url %s", s.url)
                continue

            # if it's not an image, we skip the current url
            if content_type not in self.image_formats:
                continue

            # appends to queue list
            self.queue.append(s.url)

        # shuffles the list to make it more random
        random.shuffle(self.queue)
        return len(self.queue)

    # returns the url of a photo
    def getUrl(self):
        # if somehow we did not load anything, we reload some posts
        # this should likely never happen, but might be triggered if the queue
        # has not been loaded yet
        if len(self.queue) == 0:
            self.loadPosts()

        # once in 1000 times we get a golden corgo
        if random.randint(0, 1000) == 0:
            self.updateGoldenCorgosFound()
            return self.golden_corgo_url

        url = self.queue[0]
        self.queue.append(self.queue.pop(0))  # list rotation
        return url

    # Updates number of golden corgos found and saves it to file
    def updateGoldenCorgosFound(self, count=1):
        self.golden_corgos_found += 1
        self.settings["golden_corgos_found"] = self.golden_corgos_found
        self.saveSettings()


# ---------------- COMMAND LIST AS IT IS PASSED TO @botfather --------------- #
# goldencorgo - Read the tale of this misterious creature...                  #
# corgo - When you just need a corgo                                          #
# stats - See some stats about this bot                                       #
# --------------------------------------------------------------------------- #

# this class contains all the methods and variables needed to control the
# Telegram bot
class Telegram:
    # loads settings from the settings file.
    def loadSettings(self, path="settings.json"):
        self.settings_path = path
        with open(self.settings_path) as json_file:
            # only keeps settings for Telegram, discarding others
            self.settings = json.load(json_file)["Telegram"]

        # Save settings inside variables for easier access
        self.token = self.settings["token"]
        self.admins = self.settings["admins"]
        self.corgos_sent = self.settings["corgos_sent"]
        self.time_format = self.settings["time_format"]
        self.start_date = self.settings["start_date"]

    # Saves settings into file
    def saveSettings(self):
        with open(self.settings_path) as json_file:
                old_settings = json.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Telegram"].update(self.settings)

        with open(self.settings_path, 'w') as outfile:
            json.dump(old_settings, outfile, indent=4)

    # Updates number of corgos sent and saves it to file
    def updateCorgosSent(self, count=1):
        self.corgos_sent += 1
        self.settings["corgos_sent"] = self.corgos_sent
        self.saveSettings()

    # Returns some meaningful informations needed in callbacks
    def showStatus(self):
        return {
            "admins": self.admins,
            "corgos_sent": self.corgos_sent,
            "start_date": self.start_date,
            "time_format": self.time_format
        }

    # Starts the bot
    def start(self):
        self.updater = Updater(self.token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.jobqueue = self.updater.job_queue

        # Bot start notification
        self.jobqueue.run_once(bot_started, when=0, name="bot_started")
        # Load posts for the first time
        self.jobqueue.run_once(load_posts, when=0, name="load_posts")

        # 2.20 AM GMT (timezone might change)
        job_time = time(2, 20, 0)
        # Monday and Thursday
        job_days = (0, 2, 5)
        # load new posts
        self.jobqueue.run_daily(load_posts, days=job_days,
                                time=job_time, name="load_posts")

        self.dispatcher.add_error_handler(error)

        self.dispatcher.add_handler(CommandHandler('start', start))
        self.dispatcher.add_handler(CommandHandler('stop', stop))
        self.dispatcher.add_handler(CommandHandler('reset', reset))
        self.dispatcher.add_handler(CommandHandler('corgo', corgo))
        self.dispatcher.add_handler(CommandHandler('goldencorgo', goldencorgo))
        self.dispatcher.add_handler(CommandHandler('stats', stats))
        self.dispatcher.add_handler(CommandHandler('ping', ping))

        # cathces every message and replies with some gibberish
        self.dispatcher.add_handler(MessageHandler(Filters.text, text_message))

        self.updater.start_polling()
        logging.info("Bot started")
        self.updater.idle()


# Function that sends a message to admins whenever the bot is started.
# Callback fired at startup from JobQueue
def bot_started(context: CallbackContext):
    status = t.showStatus()
    for chat_id in status["admins"]:
        message = "*Bot started*"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)


# Function that loads posts from reddit
# Callback fired at startup and at night in set days from JobQueue
def load_posts(context: CallbackContext):
    logging.info("Loading posts")
    status = t.showStatus()

    for chat_id in status["admins"]:
        message = "*Loading posts...*"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)

    posts = r.loadPosts()

    for chat_id in status["admins"]:
        message = f"*{posts} posts loaded!*"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)

    logging.info("Posts loaded")


# Function that greets user during first start
# Callback fired with command /start
def start(update, context):
    chat_id = update.effective_chat.id
    message = "_Press /corgo to get a corgo!_"
    context.bot.send_message(chat_id=chat_id, text=message,
                             parse_mode=ParseMode.MARKDOWN)


# Function that COMPLETELY stops the bot
# Callback fired with command /stop
# Hidden command as it's not the in command list
def stop(update, context):
    chat_id = update.effective_chat.id
    status = t.showStatus()

    if chat_id in status["admins"]:
        message = "_Bot stopped_"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)
        # save settings just in case
        t.saveSettings()
        t.updater.stop()
        logging.warning("Bot stopped")
        os._exit()
        exit()
    else:
        message = "*This command is for moderators only*"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)


# Function that resets the bot
# Callback fired with command /reset
# Hidden command as it's not the in command list
def reset(update, context):
    chat_id = update.effective_chat.id
    status = t.showStatus()
    if chat_id in status["admins"]:
        message = "_Resetting..._"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)

        logging.warning("Resetting")
        # System command to reload the python script
        os.execl(sys.executable, sys.executable, * sys.argv)


# Function that sends a corgo to the user
# Callback fired with command /corgo
def corgo(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    bot_username = t.updater.bot.get_me()["username"]
    caption = f"@{bot_username}"

    # Not the best way of catching errors
    # I might find a better way of checking urls but I fear it might
    #   be too slow. There's no real way to know if an image is still available
    #   unless trying to download it. So what this loop does is trying again
    #   until it works
    while True:
        try:
            url = r.getUrl()
            context.bot.send_photo(chat_id=chat_id, photo=url, caption=caption)
            break
        except:
            pass

    t.updateCorgosSent()
    message = "_Press /corgo for another corgo!_"
    context.bot.send_message(chat_id=chat_id, text=message,
                             parse_mode=ParseMode.MARKDOWN)

    logging.info("Corgo sent")


# Function that narrates the legend of the golden corgo to the user
# Callback fired with command /goldencorgo
def goldencorgo(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    bot_username = t.updater.bot.get_me()["username"].replace("_", "\\_")
    golden_corgos_found = r.showStatus()["golden_corgos_found"]

    message = (
        f"Some say that a _golden corgo_ is hiding inside Telegram... \n"
        f"All we know is that if you are lucky enough, once in maybe "
        f"1000 corgos you migh find one. \n"
        f"_So far, {golden_corgos_found} have been found "
        f"roaming this bot..._"
    )

    context.bot.send_message(chat_id=chat_id, text=message,
                             parse_mode=ParseMode.MARKDOWN)

    message = (
        f"*Maybe you too will be blessed by this elusive good boi!*\n"
        f"@{bot_username}"
    )

    context.bot.send_message(chat_id=chat_id, text=message,
                             parse_mode=ParseMode.MARKDOWN)

    logging.info("Golden corgo sent")


# Function that return stats about the bot
# Callback fired with command  /stats
def stats(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    status = t.showStatus()
    golden_corgos_found = r.showStatus()["golden_corgos_found"]

    # bot started date
    d1 = datetime.strptime(status["start_date"], status["time_format"])
    # todays date
    d2 = datetime.now()
    days_between = (d2 - d1).days + 1
    # Average number of corgos sent per day
    average = int(status["corgos_sent"] / days_between)

    message = (
        f"The bot has been running for *{days_between}* days.\n"
        f"*{status['corgos_sent']}* photos have been sent, "
        f"averaging *{average}* corgos per day!"
        f" _{random.choice(['ARF', 'WOFF', 'BORK', 'RUFF'])}_! \n"
        f"*{golden_corgos_found}* golden corgos were found!"
    )

    context.bot.send_message(chat_id=update.effective_chat.id, text=message,
                             parse_mode=ParseMode.MARKDOWN)

    logging.info("/stats called")


# Function that simply replies "PONG"
# Callback fired with command /ping for debug purposes (truth to be told, my
#   RPi zero was sometimes so bloated I was never sure if this script crashed,
#   so I wanted a way to prevent useless panicking and debugging)
# Hidden command as it's not the in command list
def ping(update, context):
    chat_id = update.effective_chat.id
    message = "🏓 *PONG* 🏓"
    context.bot.send_message(chat_id=update.effective_chat.id, text=message,
                             parse_mode=ParseMode.MARKDOWN)


# Function that sends random dog barks
# Callback fired whenever a text message is sent
# This is currently disabled in groups because it WILL lead to excessive spam.
#   In order to enable it, the "group privacy" settings in @botfather must be
#   set to "False"
def text_message(update, context):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # the dog noise list was sourced on Wikipedia. Yes, Wikipedia.
    message = f"_{random.choice(['ARF', 'WOFF', 'BORK', 'RUFF'])}!_"
    context.bot.send_message(chat_id=chat_id, text=message,
                             reply_to_message_id=message_id,
                             parse_mode=ParseMode.MARKDOWN)


# Function that logs in file and admin chat when an error occurs
# Callback fired by errors and handled by telegram module
def error(update, context):
    logging.error(context.error)
    status = t.showStatus()

    # admin message
    for chat_id in status["admins"]:
        # HECC
        message = "*ERROR RAISED*"
        context.bot.send_message(chat_id=chat_id, text=message,
                                 parse_mode=ParseMode.MARKDOWN)

    error_string = str(context.error).replace("_", "\\_")  # MARKDOWN escape
    time_string = datetime.now().strftime(status['time_format'])

    message = (
        f"Error at time: {time_string}\n"
        f"Error raised: {error_string}\n"
        f"Update: {update}"
    )

    for chat_id in status["admins"]:
        context.bot.send_message(chat_id=chat_id, text=message)

    # user message
    chat_id = update.effective_chat.id
    message = f"_Oh h*ck, the bot is doing a splish splosh_ \n *Please try again*"

    context.bot.send_message(chat_id=chat_id, text=message,
                             parse_mode=ParseMode.MARKDOWN)

    # logs to file
    logging.error('Update "%s" caused error "%s"', update, context.error)


# In order to use the Reddit object, you must
#   1) Load the settings from file with the loadSettings() method
#   2) Login into reddit with the login() method
# In order to use the Telegram object, you must
#   1) Load the settings from file with the loadSettings() method
#   2) Start the dispatcher, updater, joqueue with the start() method

# --- MAIN CODE --- #
# I didn't want to use a main function beacuse the global callbacks mess with
# the scope of the objects

# we log everything into the "corgos_bot.log" file
logging.basicConfig(filename="corgos_bot.log", level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s',
                    filemode="w+")

# Reddit section
r = Reddit()
r.loadSettings()
r.login()

# Telegram section
t = Telegram()
t.loadSettings()
t.start()
# after this, automatically calls the "load_posts" routine.
