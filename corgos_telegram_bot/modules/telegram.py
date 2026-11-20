"""Corgos BOT.

The first fully functional Telegram image bot where all the photos
    are stolen from Reddit.

Contact him on telegram @corgos_bot (direct url: t.me/corgos_bot)
This bot DOES NOT LOG every chat and user. As such, it cannot
  (and it never will) send private message to the users or groups.
Made by Lorenzo Rossi, 2019. Grazie a Giorgia per l'idea.
This code is surprisingly fully PEP8 compliant.
Yeah, I'm about as surprised as you.

MIT License - 2025, Lorenzo Rossi
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime, time
from random import choice, randint

from telegram import Update, constants
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    JobQueue,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from corgos_telegram_bot.modules.reddit import EmptyQueueError, Reddit
from corgos_telegram_bot.modules.settings import Settings

logger = logging.getLogger(__name__)

Context = ContextTypes.DEFAULT_TYPE


class Telegram:
    """This class contains all the logic for the Telegram bot."""

    _application: Application
    _jobqueue: JobQueue
    _bot_username: str
    _settings_path: str
    _settings: Settings
    _reddit: Reddit
    _stop_event: asyncio.Event
    _restart_requested: bool

    def __init__(self, settings_path: str = "settings.json") -> None:
        """Initialize the Telegram bot.

        Args:
            settings_path (str): path to the settings file
        """
        logger.info("Initializing Telegram bot")
        self._settings_path = settings_path
        # create a Reddit handler
        self._reddit = Reddit(settings_path=settings_path)
        # set when the bot is asked to stop (or restart)
        self._stop_event = asyncio.Event()
        self._restart_requested = False
        logger.info("Telegram bot initialized")

    # Private methods

    @staticmethod
    def _getChatId(update: Update) -> int:
        """Return the id of the chat an update comes from.

        Args:
            update (Update): incoming update

        Returns:
            int: id of the chat

        Raises:
            ValueError: if the update does not come from a chat
        """
        if update.effective_chat is None:
            error_msg = f"Update {update.update_id} has no chat"
            raise ValueError(error_msg)
        return update.effective_chat.id

    # Public methods

    async def start(self) -> None:
        """Start the bot."""
        logger.info("Starting bot...")
        logger.info("Loading settings...")
        self._settings = Settings(settings_path=self._settings_path)
        await self._settings.load()
        await self._settings.validate(
            [
                "telegram_token",
                "telegram_admins",
                "telegram_banned",
                "telegram_corgos_sent",
                "telegram_golden_corgos_found",
                "telegram_golden_corgo_url",
                "telegram_start_date",
                "telegram_load_days",
                "telegram_load_time",
            ]
        )

        # on which days the corgos will be fetched. Must be converted to tuple
        #   since JSON only supports arrays. 0 for sunday through 6 for saturday
        load_days = await self._settings.get("telegram_load_days", tuple)
        # minutes after midnight, UTC
        load_time = await self._settings.get(
            "telegram_load_time",
            lambda x: time(hour=x // 60, minute=x % 60, tzinfo=UTC),
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
        logger.info("Bot started")

    async def stop(self) -> None:
        """Stop the bot."""
        logger.info("Stopping bot...")
        await self._stopApplication()
        await self._reddit.stop()
        await self._settings.save()
        logger.info("Bot stopped")

    def requestStop(self, *, restart: bool = False) -> None:
        """Ask the bot to stop, letting the owner of the bot perform the shutdown.

        Args:
            restart (bool): whether the bot should be restarted after stopping.
                Defaults to False.
        """
        logger.info("Stop requested (restart: %s)", restart)
        self._restart_requested = self._restart_requested or restart
        self._stop_event.set()

    async def waitForStopRequest(self) -> None:
        """Wait until the bot is asked to stop."""
        await self._stop_event.wait()

    @property
    def restart_requested(self) -> bool:
        """Whether the bot should be restarted after stopping."""
        return self._restart_requested

    async def _setupJobQueue(self, load_time: time, load_days: tuple[int, ...]) -> None:
        logger.info("Setting up job queue...")
        if self._application.job_queue is None:
            error_msg = "Job queue not available, is the job-queue extra installed?"
            raise RuntimeError(error_msg)
        self._jobqueue = self._application.job_queue

        # bot start notification
        self._jobqueue.run_once(self._botStarted, when=0, name="bot_started")
        # load posts for the first time
        self._scheduleLoadPosts()

        # load fresh corgos on set days
        self._jobqueue.run_daily(
            self._loadPosts,
            days=load_days,
            time=load_time,
            name="load_posts",
        )
        logger.info("Job queue set up.")

    def _scheduleLoadPosts(self) -> None:
        """Load the posts from Reddit as soon as possible, in the background."""
        self._jobqueue.run_once(
            self._loadPosts,
            when=0,
            name="load_posts",
            job_kwargs={"misfire_grace_time": 60},
        )

    async def _setupHandlers(self) -> None:
        logger.info("Setting up handlers...")
        # this handler will notify the admins and the user if something went
        #   wrong during the execution
        self._application.add_error_handler(self._errorHandler)

        # these are the handlers for all the commands
        commands = {
            "start": self._botStartCommand,
            "stop": self._botStopCommand,
            "reset": self._botResetCommand,
            "corgo": self._botCorgoCommand,
            "goldencorgo": self._botGoldencorgoCommand,
            "check": self._botCheckCommand,
            "stats": self._botStatsCommand,
            "ping": self._botPingCommand,
            "ban": self._botBanCommand,
            "unban": self._botUnbanCommand,
        }
        for command, callback in commands.items():
            self._application.add_handler(CommandHandler(command, callback))

        # catches every message and replies with some gibberish
        self._application.add_handler(
            MessageHandler(
                filters.TEXT & (~filters.COMMAND),
                self._botTextMessageReceived,
            )
        )
        logger.info("Handlers set up.")

    async def _startApplication(self) -> None:
        """Start the application.

        Raises:
            RuntimeError: if the application has no updater
        """
        await self._application.initialize()
        # the bot info is fetched during the initialization
        self._bot_username = f"@{self._application.bot.username}"
        logger.info("Bot username is %s", self._bot_username)

        if self._application.updater is None:
            error_msg = "Updater not available"
            raise RuntimeError(error_msg)
        await self._application.updater.start_polling()
        await self._application.start()

    async def _stopApplication(self) -> None:
        """Stop the application.

        Stopping the updater also marks the updates that have already been
        received as read, so they are not delivered again after a restart.
        """
        if self._application.updater is not None:
            await self._application.updater.stop()
        await self._application.stop()
        await self._application.shutdown()

    async def _getAdmins(self) -> list[int]:
        """Get the list of admin chat ids.

        Returns:
            list[int]: list of admin chat ids
        """
        return await self._settings.get("telegram_admins")

    async def _notifyAdmins(
        self,
        message: str,
        parse_mode: str | None = constants.ParseMode.MARKDOWN,
    ) -> None:
        """Send a message to all the admins.

        A failure to reach an admin (e.g. if they blocked the bot) is logged
        and does not prevent the other admins from being notified.

        Args:
            message (str): text of the message
            parse_mode (str | None): parse mode of the message.
                Defaults to markdown.
        """
        for chat_id in await self._getAdmins():
            try:
                await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=parse_mode,
                )
            except TelegramError as e:
                logger.warning("Cannot notify admin %d: %s", chat_id, e)

    # Callbacks

    async def _botStarted(self, _context: Context) -> None:
        """Send a message to admins when the bot starts.

        Callback fired at startup from JobQueue
        """
        await self._notifyAdmins("*Bot started*")

    async def _loadPosts(self, _context: Context) -> None:
        """Load posts from Reddit.

        Callback fired at startup and at night in set days from JobQueue
        """
        logger.info("Loading posts asynchronously.")
        await self._notifyAdmins("_Posts are now being loaded..._")

        logger.info("Downloading posts from Reddit.")
        posts_num = await self._reddit.loadPostsAsync()
        logger.info("Downloaded %d posts from Reddit.", posts_num)

        await self._notifyAdmins(f"_{posts_num} posts have been loaded._")
        logger.info("Posts loaded.")

    async def _botStartCommand(self, update: Update, context: Context) -> None:
        """Greet the user when /start is called.

        Callback fired with command /start
        """
        chat_id = self._getChatId(update)
        message = "_Press /corgo to get a corgo!_"
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logger.info("/start called")

    async def _botStopCommand(self, update: Update, context: Context) -> None:
        """Completely stops the bot.

        Callback fired with command /stop
        Hidden command as it's not the in command list
        """
        chat_id = self._getChatId(update)

        admins = await self._getAdmins()
        if chat_id in admins:
            message = "_Bot stopped_"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            logger.warning("Stopped by chat id %d", chat_id)
            # the bot cannot be stopped from inside a handler, as stopping
            #   waits for all the handlers to finish
            self.requestStop()

        else:
            message = "*This command is for moderators only*"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )

    async def _botResetCommand(self, update: Update, context: Context) -> None:
        """Reset the bot.

        Callback fired with command /reset
        Hidden command as it's not the in command list
        """
        chat_id = self._getChatId(update)
        admins = await self._getAdmins()
        if chat_id in admins:
            message = "_Resetting..._"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )

            logger.warning("Reset by chat id %d", chat_id)
            # the bot is stopped gracefully and then the script is reloaded
            self.requestStop(restart=True)

    async def _replyOutOfCorgos(self, chat_id: int, context: Context) -> None:
        """Notify the user that there are no corgos and start loading them."""
        message = "_The bot is currently out of corgos!_\n_Wait a bit and try again._"
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        if not self._reddit.is_loading:
            # if the bot is not already loading, we want to load posts
            #   asynchronously
            self._scheduleLoadPosts()

    async def _botCorgoCommand(self, update: Update, context: Context) -> None:
        """Send a corgo to the user.

        Callback fired with command /corgo
        """
        chat_id = self._getChatId(update)
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
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return

        try:
            url = await self._reddit.getUrl()
        except EmptyQueueError:
            # if the queue is empty, we want to notify the user
            await self._replyOutOfCorgos(chat_id, context)
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
            message = escape_markdown(self._bot_username)

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
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logger.info("Corgo sent")

    async def _botGoldencorgoCommand(self, update: Update, context: Context) -> None:
        """Narrate the legend of the golden corgo to the user.

        Callback fired with command /goldencorgo
        """
        chat_id = self._getChatId(update)
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=constants.ChatAction.TYPING,
        )

        golden_corgos_found = await self._settings.get("telegram_golden_corgos_found")

        message = (
            "Some say that a _golden corgo_ is hiding inside Telegram... \n"
            "All we know is that if you are lucky enough, once in maybe "
            "1000 corgos you might find one. \n"
            f"_So far, {golden_corgos_found} have been found "
            "roaming this bot..._"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        username = escape_markdown(self._bot_username)
        message = (
            f"*Maybe you too will be blessed by this elusive good boi!*\n{username}"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logger.info("/goldencorgo called")

    async def _botCheckCommand(self, update: Update, context: Context) -> None:
        """Check if the golden corgo picture is still available.

        Callback fired with command /check
        Hidden command as it's not the in command list

        Raises:
            TelegramError: if the golden corgo picture is not found
        """
        chat_id = self._getChatId(update)

        admins = await self._getAdmins()
        if chat_id not in admins:
            message = "*This command is for moderators only*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        url = await self._settings.get("telegram_golden_corgo_url")
        # we want to get the "small" image in order to make this
        # whole process  slightly faster. imgur provides different
        # image sizes by editing its url a bit
        small_url = url.replace(".jpg", "s.jpg")

        try:
            sent = await context.bot.send_photo(
                chat_id=chat_id,
                photo=small_url,
                caption=self._bot_username,
            )
        except TelegramError:
            message = "*Golden Corgo picture not found!*\n"
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            # the error handler will send the details to the admins
            raise

        message = "*The golden corgo URL is still working!*"
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        # we now delete the sent picture to keep the SECRET
        await context.bot.delete_message(chat_id, sent.message_id)

        logger.info("/check called")

    async def _botStatsCommand(self, update: Update, context: Context) -> None:
        """Return stats about the bot.

        Callback fired with command  /stats
        """
        chat_id = self._getChatId(update)
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        # bot started date, stored in UTC
        d1 = await self._settings.get(
            "telegram_start_date",
            lambda x: datetime.fromisoformat(x).replace(tzinfo=UTC),
        )
        # today's date
        d2 = datetime.now(UTC)
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
            chat_id=chat_id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logger.info("/stats called")

    async def _botPingCommand(self, update: Update, context: Context) -> None:
        """Reply "PONG" to the user.

        Callback fired with command /ping for debug purposes
        Hidden command as it's not the in command list
        """
        message = "🏓 *PONG* 🏓"
        await context.bot.send_message(
            chat_id=self._getChatId(update),
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

    @staticmethod
    async def _parseChatIds(chat_id: int, context: Context) -> set[int] | None:
        """Parse the chat ids passed as arguments to a command.

        If the arguments are not valid, the user is notified.

        Args:
            chat_id (int): id of the chat the command was sent from
            context (Context): context of the command

        Returns:
            set[int] | None: the parsed chat ids, None if they are not valid
        """
        try:
            return {int(arg) for arg in context.args or []}
        except ValueError:
            message = "*Chat ids must be numbers*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            return None

    async def _botBanCommand(self, update: Update, context: Context) -> None:
        """Ban a chat from the bot.

        Hidden command as it's not the in command list
        """
        chat_id = self._getChatId(update)

        admins = await self._getAdmins()
        if chat_id in admins:
            to_ban = await self._parseChatIds(chat_id, context)
            if to_ban is None:
                return

            banned_chats = await self._settings.apply(
                "telegram_banned", lambda banned: sorted(set(banned) | to_ban)
            )
            if len(banned_chats) > 0:
                message = "_Ban list_: " + ", ".join(str(b) for b in banned_chats)
            else:
                message = "_Ban list is empty_"

        else:
            message = "*This command is for moderators only*"

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

    async def _botUnbanCommand(self, update: Update, context: Context) -> None:
        """Unban a chat from the bot.

        Hidden command as it's not the in command list
        """
        chat_id = self._getChatId(update)

        admins = await self._getAdmins()
        if chat_id in admins:
            to_unban = await self._parseChatIds(chat_id, context)
            if to_unban is None:
                return

            await self._settings.apply(
                "telegram_banned", lambda banned: sorted(set(banned) - to_unban)
            )

            message = "*Chats removed from ban list*: " + ", ".join(
                str(a) for a in sorted(to_unban)
            )
        else:
            message = "*This command is for moderators only*"

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

    async def _botTextMessageReceived(self, update: Update, context: Context) -> None:
        """Send a random dog bark when a text message is received.

        Callback fired whenever a text message is sent
        This is currently disabled in groups because it WILL lead to excessive
        spam. In order to enable it, the "group privacy" settings in
        @botfather must be set to "False"
        """
        if not update.message or not update.message.text:
            return

        chat_id = self._getChatId(update)
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
        # if the message contains a "bark", we want to reply accordingly
        elif bark := next((b.strip() for b in barks if b.strip() in message_text), ""):
            message = f"_{bark}!_"
        # if the message contains the word "corgo", we want to tell the user
        #   to use the correct command
        elif "CORGO" in message_text:
            message = "_Press /corgo to get a corgo!_"
        else:
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

    async def _errorHandler(self, update: object, context: Context) -> None:
        """Send a message to admins whenever an error is raised."""
        error_string = str(context.error)
        update_string = str(update)
        time_string = datetime.now(UTC).isoformat(sep=" ")

        tb_list = traceback.format_exception(context.error)
        tb_string = "".join(tb_list)

        messages = [
            f"Error at time: {time_string}\n",
            f"Error raised: {error_string}\n",
            f"Update: {update_string}",
            f"Traceback:\n{tb_string}",
        ]

        # telegram messages have a maximum length, longer ones must be split
        max_length = constants.MessageLimit.MAX_TEXT_LENGTH
        for message in messages:
            for start in range(0, len(message), max_length):
                await self._notifyAdmins(
                    message[start : start + max_length], parse_mode=None
                )

        # log to file
        logger.error("Update %s caused error %s.", update_string, error_string)
        logger.error("Traceback:\n%s", tb_string)
