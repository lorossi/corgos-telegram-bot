"""Corgos BOT, a fully functional Telegram image bot where all the photos are stolen from Reddit.

Contact him on telegram @corgos_bot (direct url: t.me/corgos_bot)
This bot DOES NOT LOG every chat and user. As such, it cannot
  (and it never will) send private message to the users or groups.
Made by Lorenzo Rossi, 2019. Grazie a Giorgia per l'idea.
This code is surprisingly fully PEP8 compliant.
Yeah, I'm about as surprised as you.

MIT License - 2025, Lorenzo Rossi
"""

import logging
import os
import sys
import traceback
from datetime import datetime, time
from random import choice, randint

from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from modules.reddit import Reddit
from modules.settings import Settings


class Telegram:
    """This class contains all the methods and variables needed to control the Telegram bot."""

    _settings: Settings
    _settings_path: str = "settings.json"
    _reddit: Reddit

    def __init__(self) -> None:
        """Init the bot, loading the settings as well."""
        self._settings = {}
        self._settings_path = "settings.json"
        # create a Reddit handler
        self._reddit = Reddit()
        # preload the username for faster access
        self._bot_username = None

    # Private methods

    def _escapeMarkdown(self, text: str) -> str:
        """Escape markdown characters in a text.

        Args:
            text (str): text to escape
        """
        to_escape = ["_", "*", "[", "]", "(", ")"]
        for char in to_escape:
            text = text.replace(char, f"\\{char}")
        return text

    # Public methods

    async def start(self) -> None:
        """Start the bot."""
        self._settings = Settings(self._settings_path)
        await self._settings.load()

        # on which days the corgos will be fetched. Must be converted to tuple
        #   since JSON only supports arrays. 0 for monday through 6 for sunday
        load_days = await self._settings.get("telegram_load_days", lambda x: tuple(x))
        load_time = await self._settings.get(
            "telegram_load_time", lambda x: time(minute=x % 60, hour=int(x / 60))
        )
        token = await self._settings.get("telegram_token")

        self._application = Application.builder().token(token).build()

        # setup the job queue
        await self._setupJobQueue(load_time, load_days)

        # add command handlers
        await self._setupHandlers()

        # Log in into reddit
        await self._reddit.start()

        # start the application
        await self._startApplication()
        logging.info("Bot started")

    async def stop(self) -> None:
        """Stop the bot."""
        await self._stopApplication()
        await self._reddit.stop()
        await self._settings.save()
        logging.info("Bot stopped")

    async def _setupJobQueue(self, load_time: int, load_days: tuple[int]) -> None:
        self._jobqueue = self._application.job_queue

        # bot start notification
        self._jobqueue.run_once(self._botStarted, when=0, name="bot_started")
        # load posts for the first time
        self._jobqueue.run_once(
            self._loadPosts,
            when=0,
            name="load_posts",
            job_kwargs={"misfire_grace_time": 60},
        )
        # preload the username for faster access
        self._jobqueue.run_once(
            self._preloadUsername,
            when=0,
            name="preload_username",
            job_kwargs={"misfire_grace_time": 60},
        )

        # load fresh corgos on set days
        self._jobqueue.run_daily(
            self._loadPosts,
            days=load_days,
            time=load_time,
            name="load_posts",
        )

    async def _setupHandlers(self) -> None:
        # this handler will notify the admins and the user if something went
        #   wrong during the execution
        self._application.add_error_handler(self._errorHandler)

        # these are the handlers for all the commands
        self._application.add_handler(CommandHandler("start", self._botStartCommand))
        self._application.add_handler(CommandHandler("stop", self._botStopCommand))
        self._application.add_handler(CommandHandler("reset", self._botResetCommand))
        self._application.add_handler(CommandHandler("corgo", self._botCorgoCommand))

        self._application.add_handler(
            CommandHandler("goldencorgo", self._botGoldencorgoCommand)
        )
        self._application.add_handler(CommandHandler("check", self._botCheckCommand))
        self._application.add_handler(CommandHandler("stats", self._botStatsCommand))
        self._application.add_handler(CommandHandler("ping", self._botPingCommand))
        self._application.add_handler(CommandHandler("ban", self._botBanCommand))
        self._application.add_handler(CommandHandler("unban", self._botUnbanCommand))

        # catches every message and replies with some gibberish
        self._application.add_handler(
            MessageHandler(
                filters.TEXT & (~filters.COMMAND), self._botTextMessageReceived
            )
        )

    async def _startApplication(self) -> None:
        """Start the application."""
        await self._application.initialize()
        await self._application.updater.start_polling()
        await self._application.start()

    async def _stopApplication(self) -> None:
        """Stop the application."""
        await self._application.updater.stop()
        await self._application.stop()
        await self._application.shutdown()

    async def _getAdmins(self) -> list[int]:
        """Get the list of admin chat ids."""
        admins = await self._settings.get("telegram_admins")
        return admins

    # Callbacks

    async def _botStarted(self, context: ContextTypes) -> None:
        """Send a message to admins when the bot starts.

        Callback fired at startup from JobQueue
        """
        message = "*Bot started*"
        admins = await self._getAdmins()
        for chat_id in admins:
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

    async def _loadPosts(self, context: ContextTypes) -> None:
        """Load posts from Reddit.

        Callback fired at startup and at night in set days from JobQueue
        """
        logging.info("Loading posts asynchronously.")

        message = "_Posts are now being loaded..._"
        admins = await self._getAdmins()
        for chat_id in admins:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )

        logging.info("Downloading posts from Reddit.")
        posts = await self._reddit.loadPostsAsync()
        logging.info(f"Downloaded {posts} posts from Reddit.")

        message = f"_{posts} posts have been loaded._"
        for chat_id in admins:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        logging.info("Posts loaded.")

    async def _preloadUsername(self, _: ContextTypes) -> None:
        # load the bot username
        logging.info("Preloading bot username.")
        me = await self._application.bot.get_me()
        self._bot_username = "@" + me.username
        logging.info(f"Bot username is {self._bot_username}")

    async def _botStartCommand(self, update: Update, context: ContextTypes) -> None:
        """Greet the user when /start is called.

        Callback fired with command /start
        """
        chat_id = update.effective_chat.id
        message = "_Press /corgo to get a corgo!_"
        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("/start called")

    async def _botStopCommand(self, update: Update, context: ContextTypes) -> None:
        """Completely stops the bot.

        Callback fired with command /stop
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id

        admins = await self._getAdmins()
        if chat_id in admins:
            message = "_Bot stopped_"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            # save settings just in case
            self._saveSettings()
            logging.warning(f"Stopped by chat id {chat_id}")
            await self._stopApplication()
            sys.exit(0)

        else:
            message = "*This command is for moderators only*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

    async def _botResetCommand(self, update: Update, context: ContextTypes) -> None:
        """Reset the bot.

        Callback fired with command /reset
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id
        admins = await self._getAdmins()
        if chat_id in admins:
            message = "_Resetting..._"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

            logging.warning(f"Reset by chat id {chat_id}")
            # System command to reload the python script
            os.execl(sys.executable, sys.executable, *sys.argv)

    async def _botCorgoCommand(self, update: Update, context: ContextTypes) -> None:
        """Send a corgo to the user.

        Callback fired with command /corgo
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )
        banned_chats = await self._settings.get("telegram_banned")
        if chat_id in banned_chats:
            message = (
                "*You have been banned by the bot.*"
                "\nThink about your past mistakes. \n\n_Hecc_."
            )
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        if await self._reddit.getQueueSize() == 0:
            # if the queue is empty, we want to notify the user
            message = (
                "_The bot is currently out of corgos!_\n_Wait a bit and try again._"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )

            if not self._reddit.is_loading:
                # if the bot is not already loading, we want to load posts
                #   asynchronously
                self._jobqueue.run_once(
                    self._loadPosts,
                    when=0,
                    name="load_posts",
                    job_kwargs={"misfire_grace_time": 60},
                )

            return

        if randint(1, 1000) == 1:
            # if we are lucky enough, we get a golden corgo!
            url = await self._settings.get("telegram_golden_corgo_url")
            await self._settings.apply(
                "telegram_golden_corgos_found",
                lambda x: x + 1,
            )
            message = "\n*GOLDEN CORGO FOUND!*"
        else:
            # otherwise we get a normal corgo
            url = await self._reddit.getUrl()
            message = self._escapeMarkdown(self._bot_username)

        # increase the corgo counter
        await self._settings.apply(
            "telegram_corgos_sent",
            lambda x: x + 1,
        )

        # send the corgo to the user
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=url,
            caption=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        # send another message to the user
        message = "_Press /corgo for another corgo!_"
        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("Corgo sent")

    async def _botGoldencorgoCommand(
        self, update: Update, context: ContextTypes
    ) -> None:
        """Narrate the legend of the golden corgo to the user.

        Callback fired with command /goldencorgo
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        golden_corgos_found = await self._settings.get("telegram_golden_corgos_found")

        message = (
            f"Some say that a _golden corgo_ is hiding inside Telegram... \n"
            f"All we know is that if you are lucky enough, once in maybe "
            f"1000 corgos you might find one. \n"
            f"_So far, {golden_corgos_found} have been found "
            f"roaming this bot..._"
        )

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        username = self._escapeMarkdown(self._bot_username)
        message = (
            f"*Maybe you too will be blessed by this elusive good boi!*\n{username}"
        )

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("/goldencorgo called")

    async def _botCheckCommand(self, update: Update, context: ContextTypes) -> None:
        """Check if the golden corgo picture is still available.

        Callback fired with command /check
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id

        admins = await self._getAdmins()
        url = await self._settings.get("telegram_golden_corgo_url")
        if chat_id in admins:
            # we want to get the "small" image in order to make this
            # whole process  slightly faster. imgur provides different
            # image sizes by editing its url a bit
            small_url = url.replace(".jpg", "s.jpg")

            caption = self._bot_username

            try:
                m = await context.bot.send_photo(
                    chat_id=chat_id, photo=small_url, caption=caption
                )
                to_delete = m["message_id"]

                message = "*The golden corgo URL is still working!*"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )

            except Exception as e:
                message = "*Golden Corgo picture not found!*\n"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                log = f"Error while sending checking golden corgo. Url {url} Error {e}"
                logging.error(log)
                raise Exception(f"Url {url} is not a valid golden corgo url!")

            # we now delete the sent messages (if any) to keep the SECRET
            if to_delete:
                await context.bot.delete_message(chat_id, to_delete)

        else:
            message = "*This command is for moderators only*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

        logging.info("/check called")

    async def _botStatsCommand(self, update: Update, context: ContextTypes) -> None:
        """Return stats about the bot.

        Callback fired with command  /stats
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        # bot started date
        d1 = await self._settings.get(
            "telegram_start_date",
            lambda x: datetime.fromisoformat(x),
        )
        # today's date
        d2 = datetime.now()
        days_between = (d2 - d1).days + 1
        # Average number of corgos sent per day
        corgos_sent = await self._settings.get("telegram_corgos_sent")
        average = int(corgos_sent / days_between)
        # golden corgos found
        golden_corgos_found = await self._settings.get("telegram_golden_corgos_found")

        message = (
            f"The bot has been running for *{days_between}* days.\n"
            f"*{corgos_sent}* photos have been sent, "
            f"averaging *{average}* corgos per day!"
            f" _{choice(['ARF', 'WOFF', 'BORK', 'RUFF'])}_!\n"
            f"*{golden_corgos_found}* golden corgos were found!"
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logging.info("/stats called")

    async def _botPingCommand(self, update: Update, context: ContextTypes) -> None:
        """Reply "PONG" to the user.

        Callback fired with command /ping for debug purposes
        Hidden command as it's not the in command list
        """
        message = "🏓 *PONG* 🏓"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    async def _botBanCommand(self, update: Update, context: ContextTypes) -> None:
        """Ban a chat from the bot.

        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id
        message = ""

        admins = await self._getAdmins()
        banned = await self._settings.get("telegram_banned")
        if chat_id in admins:
            for arg in context.args:
                banned.append(int(arg))

            await self._settings.set("telegram_banned", sorted(set(banned)))
            banned_chats = await self._settings.get("telegram_banned")
            if len(banned_chats) > 0:
                message = "_Ban list_: " + ", ".join(str(b) for b in banned_chats)
            else:
                message = "_Ban list is empty_"

        else:
            message = "*This command is for moderators only*"

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

    async def _botUnbanCommand(self, update: Update, context: ContextTypes) -> None:
        chat_id = update.effective_chat.id
        message = ""

        admins = await self._getAdmins()
        banned = await self._settings.get("telegram_banned")
        if chat_id in admins:
            for arg in context.args:
                banned.remove(int(arg))

            await self._settings.set("telegram_banned", sorted(set(banned)))

            message = "*Chats removed from ban list*: " + ", ".join(
                str(a) for a in context.args
            )
        else:
            message = "*This command is for moderators only*"

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

    # Function that sends random dog barks
    # Callback fired whenever a text message is sent
    # This is currently disabled in groups because it WILL lead to
    #   excessive spam.
    #  In order to enable it, the "group privacy" settings in @botfather
    #  must be set to "False"

    async def _botTextMessageReceived(
        self, update: Update, context: ContextTypes
    ) -> None:
        """Send a random dog bark when a text message is received.

        Callback fired whenever a text message is sent
        This is currently disabled in groups because it WILL lead to excessive
        spam. In order to enable it, the "group privacy" settings in
        @botfather must be set to "False"
        """
        if not update.message:
            return

        chat_id = update.effective_chat.id
        message_id = update.message.message_id

        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        message_text = update.message.text.upper()
        barks = ["ARF ", "WOFF ", "BORK ", "RUFF "]
        swearwords = ["HECK", "GOSH", "DARN", "SHOOT", "FRICK", "FLIP"]
        marks = ["!", "?", "!?", "?!"]

        # if the message is a "swear word", we want to notify the user that we
        #   don't tolerate it here
        if any(s in message_text for s in swearwords):
            message = "_NO H*CKING BAD LANGUAGE HERE!_"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_to_message_id=message_id,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        # if the message contains a "bark", we want to reply accordingly
        for b in barks:
            if b.strip() in message_text:
                message = f"_{b.strip()}!_"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_to_message_id=message_id,
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
                return

        # if the message contains the word "corgo", we want to tell the user
        #   to use the correct command
        if "CORGO" in message_text.upper():
            message = "_Press /corgo to get a corgo!_"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                reply_to_message_id=message_id,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        # we want to generate some gibberish answer to every message
        # the dog noise list was sourced on Wikipedia. Yes, Wikipedia.
        bark = choice(barks)
        bark *= randint(1, 2)  # get some repetition
        bark = bark.rstrip()  # remove the last space (if any)
        mark = choice(marks)
        message = f"_{bark}{mark}_"
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_to_message_id=message_id,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    async def _errorHandler(self, update: Update, context: ContextTypes):
        """Send a message to admins whenever an error is raised."""
        error_string = str(context.error)
        update_string = str(update)
        time_string = datetime.now().isoformat(sep=" ")

        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        tb_string = " ".join(tb_list)

        messages = [
            f"Error at time: {time_string}\n",
            f"Error raised: {error_string}\n",
            f"Update: {update_string}",
            f"Traceback:\n{tb_string}",
        ]

        admins = await self._getAdmins()
        for chat_id in admins:
            for message in messages:
                await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                )

        # log to file
        logging.error(f"Update {update} caused error {context.error}.")
        logging.error(f"Traceback:\n{tb_string}")
