"""
Corgos BOT, a fully functional Telegram image bot where all the photos \
  are stolen from Reddit.

Contact him on telegram @corgos_bot (direct url: t.me/corgos_bot)
This bot DOES NOT LOG every chat and user. As such, it cannot \
  (and it never will) send private message to the users or groups.
Made by Lorenzo Rossi, 2019. Grazie a Giorgia per l'idea.
This code is surprisingly fully PEP8 compliant.
Yeah, I'm about as surprised as you.
License: Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)
"""

import os
import sys
import ujson
import logging
import traceback, tracemalloc

from reddit import Reddit

from random import choice, randint
from datetime import datetime, time
from telegram import Update, constants
from telegram.ext import (
    CommandHandler,
    CallbackContext,
    MessageHandler,
    filters,
    Application,
)


class Telegram:
    """This class contains all the methods and variables needed to \
        control the Telegram bot."""

    def __init__(self) -> None:
        """Init the bot, loading the settings as well."""
        self._settings = {}
        self._settings_path = "settings.json"
        # load all the settings
        self._loadSettings()
        # create a Reddit handler
        self._reddit = Reddit()

    # Private methods

    def _loadSettings(self) -> None:
        """Load settings from the settings file."""
        with open(self._settings_path) as json_file:
            # only keeps settings for Telegram, discarding others
            self._settings = ujson.load(json_file)["Telegram"]

        # on which days the corgos will be fetched. Must be converted to tuple
        #   since JSON only supports arrays. 0 for monday through 6 for sunday
        self._load_days = tuple(self._settings["load_days"])

        # load time expressed in minutes after midnight (GMT time)
        self._load_time = time(
            minute=self._settings["load_time"] % 60,
            hour=int(self._settings["load_time"] / 60),
        )

    def _saveSettings(self) -> None:
        """Save settings into file."""
        with open(self._settings_path) as json_file:
            old_settings = ujson.load(json_file)

        # since settings is a dictionary, we update the settings loaded
        # with the current settings dict
        old_settings["Telegram"].update(self._settings)

        with open(self._settings_path, "w") as outfile:
            ujson.dump(old_settings, outfile, indent=2)

    def _updateCorgosSent(self) -> None:
        """Update number of corgos sent and save to file."""
        self._corgos_sent += 1
        self._settings["corgos_sent"] = self._corgos_sent
        self._saveSettings()

    def _addToBanned(self, chat_id: int) -> None:
        """Add a chat_id to the banned list.

        Args:
            chat_id (int): id of the chat to ban
        """
        if len(self._banned_chats) > 0:
            # list already exists
            already_banned = self._banned_chats
            already_banned.append(chat_id)
            self._settings["banned"] = list(set(self._settings["banned"]))
        else:
            # list doesn't exist yet
            self._banned_chats = [chat_id]
        # save to file
        self._saveSettings()

    def _removeFromBanned(self, chat_id: int) -> None:
        """Remove a chat_id from the banned list.

        Args:
            chat_id (int): chat_id
        """
        if chat_id in self._settings["banned"]:
            self._settings["banned"].remove(chat_id)
        # save to file
        self._saveSettings()

    # Public methods

    def start(self) -> None:
        """Start the bot."""
        self._application = Application.builder().token(self._settings["token"]).build()

        self._jobqueue = self._application.job_queue

        # bot start notification
        self._jobqueue.run_once(self._botStarted, when=0, name="bot_started")
        # load posts for the first time
        self._jobqueue.run_once(self._loadPosts, when=0, name="load_posts")

        # load fresh corgos on set days
        self._jobqueue.run_daily(
            self._loadPosts,
            days=self._load_days,
            time=self._load_time,
            name="load_posts",
        )

        # this handler will notify the admins and the user if something went
        #   wrong during the execution
        self._application.add_error_handler(self._botError)

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

        # Log in into reddit
        self._reddit.login()

        # blocking instructions
        self._application.run_polling()
        logging.info("Bot started")

    # Setters and getters

    @property
    def _admins(self) -> list[int]:
        return self._settings["admins"]

    @property
    def _escaped_bot_username(self) -> str:
        return self._bot_username.replace("_", "\_")

    @property
    def _corgos_sent(self) -> int:
        return self._settings["corgos_sent"]

    @_corgos_sent.setter
    def _corgos_sent(self, value: int) -> None:
        self._settings["corgos_sent"] = value
        self._saveSettings()

    @property
    def _start_date(self) -> datetime:
        return self._settings["start_date"]

    @property
    def _golden_corgos_found(self) -> int:
        return self._settings["golden_corgos_found"]

    @_golden_corgos_found.setter
    def _golden_corgos_found(self, value):
        self._settings["golden_corgos_found"] = value
        self._saveSettings()

    @property
    def _golden_corgo_url(self) -> str:
        return self._settings["golden_corgo_url"]

    @property
    def _banned_chats(self) -> list[int]:
        return self._settings["banned"]

    @_banned_chats.setter
    def _banned_chats(self, chats: list[int]) -> None:
        self._settings["banned"] = list(set(chats))
        self._saveSettings()

    # Callbacks

    async def _botStarted(self, context: CallbackContext) -> None:
        """Send a message to admins when the bot starts.

        Callback fired at startup from JobQueue
        """
        message = "*Bot started*"
        for chat_id in self._admins:
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

        # load username
        me = await self._application.bot.get_me()
        self._bot_username = me.username

    async def _loadPosts(self, context: CallbackContext) -> None:
        """Load posts from Reddit.

        Callback fired at startup and at night in set days from JobQueue
        """
        logging.info("Loading posts")

        for chat_id in self._admins:
            message = "*Loading posts...*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

        posts = await self._reddit.loadPosts()
        message = f"*{posts} posts loaded!*"

        for chat_id in self._admins:
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

        logging.info("Posts loaded")

    async def _botStartCommand(self, update: Update, context: CallbackContext) -> None:
        """Greet the user when /start is called.

        Callback fired with command /start
        """
        chat_id = update.effective_chat.id
        message = "_Press /corgo to get a corgo!_"
        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("/start called")

    async def _botStopCommand(self, update: Update, context: CallbackContext) -> None:
        """Completely stops the bot.

        Callback fired with command /stop
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id

        if chat_id in self._admins:
            message = "_Bot stopped_"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            # save settings just in case
            self._saveSettings()
            self._application.stop()
            logging.warning(f"Stopped by chat id {chat_id}")
            os._exit(0)

        else:
            message = "*This command is for moderators only*"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

    async def _botResetCommand(self, update: Update, context: CallbackContext) -> None:
        """Reset the bot.

        Callback fired with command /reset
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id

        if chat_id in self._admins:
            message = "_Resetting..._"
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

            logging.warning(f"Reset by chat id {chat_id}")
            # System command to reload the python script
            os.execl(sys.executable, sys.executable, *sys.argv)

    async def _botCorgoCommand(self, update: Update, context: CallbackContext) -> None:
        """Send a corgo to the user.

        Callback fired with command /corgo
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        if chat_id in self._banned_chats:
            message = (
                "*You have been banned by the bot.*"
                "\nThink about your past mistakes. \n\n_Hecc_."
            )
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        caption = f"@{self._bot_username}"

        if randint(0, 1000) == 0:
            # send a golden corgo
            url = self._golden_corgo_url
            await context.bot.send_photo(chat_id=chat_id, photo=url, caption=caption)
            self._golden_corgos_found += 1
        else:
            # not the best way of catching errors
            # I might find a better way of checking urls but I fear it might
            #   be too slow. There's no real way to know if an image is still
            #   available unless trying to send it.
            # It shouldn't happen often, but the method I used previously
            # managed to crash both the script and the RaspberryPi
            try:
                url = self._reddit.getImage()
                await context.bot.send_photo(
                    chat_id=chat_id, photo=url, caption=caption
                )
            except Exception as e:
                logging.error(f"Error while sending photo. Url {url} Error {e}")
                if "flood" not in str(e).lower():
                    self._reddit.removeImage(url)
                raise Exception(f"Url {url} is not valid. Error {e}")
                # at this point, an exception is raised and the error
                #   function is called. The user gets notified and
                #   prompted to try again.
                # The image gets then remove from the queue

        self._corgos_sent += 1
        message = "_Press /corgo for another corgo!_"
        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("Corgo sent")

    async def _botGoldencorgoCommand(
        self, update: Update, context: CallbackContext
    ) -> None:
        """Narrate the legend of the golden corgo to the user.

        Callback fired with command /goldencorgo
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        message = (
            f"Some say that a _golden corgo_ is hiding inside Telegram... \n"
            f"All we know is that if you are lucky enough, once in maybe "
            f"1000 corgos you might find one. \n"
            f"_So far, {self._golden_corgos_found} have been found "
            f"roaming this bot..._"
        )

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        message = (
            f"*Maybe you too will be blessed by this elusive good boi!*\n"
            f"@{self._escaped_bot_username}"
        )

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

        logging.info("/goldencorgo called")

    async def _botCheckCommand(self, update: Update, context: CallbackContext) -> None:
        """Check if the golden corgo picture is still available.

        Callback fired with command /check
        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id

        if chat_id in self._admins:
            url = self._golden_corgo_url

            # we want to get the "small" image in order to make this
            # whole process  slightly faster. imgur provides different
            # image sizes by editing its url a bit
            small_url = url.replace(".jpg", "s.jpg")

            caption = f"@{self._bot_username}"

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
                log = (
                    f"Error while sending checking golden corgo. "
                    f"Url {url} Error {e}"
                )
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

    async def _botStatsCommand(self, update: Update, context: CallbackContext) -> None:
        """Return stats about the bot.

        Callback fired with command  /stats
        """
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        # bot started date
        d1 = datetime.fromisoformat(self._settings["start_date"])
        # today's date
        d2 = datetime.now()
        days_between = (d2 - d1).days + 1
        # Average number of corgos sent per day
        average = int(self._corgos_sent / days_between)

        message = (
            f"The bot has been running for *{days_between}* days.\n"
            f"*{self._corgos_sent}* photos have been sent, "
            f"averaging *{average}* corgos per day!"
            f" _{choice(['ARF', 'WOFF', 'BORK', 'RUFF'])}_! \n"
            f"*{self._golden_corgos_found}* golden corgos were found!"
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode=constants.ParseMode.MARKDOWN,
        )

        logging.info("/stats called")

    async def _botPingCommand(self, update: Update, context: CallbackContext) -> None:
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

    async def _botBanCommand(self, update: Update, context: CallbackContext) -> None:
        """Ban a chat from the bot.

        Hidden command as it's not the in command list
        """
        chat_id = update.effective_chat.id
        message = ""

        if chat_id in self._admins:
            for arg in context.args:
                self._addToBanned(int(arg))

            if len(self._banned_chats) > 0:
                message = "_Ban list_: " + ", ".join(str(b) for b in self._banned_chats)
            else:
                message = "_Ban list is empty_"

        else:
            message = "*This command is for moderators only*"

        await context.bot.send_message(
            chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
        )

    async def _botUnbanCommand(self, update: Update, context: CallbackContext) -> None:
        chat_id = update.effective_chat.id
        message = ""

        if chat_id in self._admins:
            for arg in context.args:
                self._removeFromBanned(int(arg))

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
        self, update: Update, context: CallbackContext
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

    async def _botError(self, update: Update, context: CallbackContext) -> None:
        """Log errors caused by updates.

        Callback fired whenever a text message is sent
        Callback fired by errors and handled by telegram module
        """
        logging.error(f"Exception while handling an update: {context.error}")
        tb_list = traceback.format_exception(
            None, context.error, context.error.__traceback__
        )
        logging.error(f"Traceback: {''.join(tb_list)}")

        logging.error(context.error)

        message = "*ERROR RAISED*"
        # admin message
        for chat_id in self._admins:
            # HECC
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                disable_web_page_preview=True,
                parse_mode=constants.ParseMode.MARKDOWN,
            )

        error_string = str(context.error)
        time_string = datetime.now().isoformat()

        message = (
            f"Error at time: {time_string}\n"
            f"Error raised: {error_string}\n"
            f"Update: {update}"
        )

        for chat_id in self._admins:
            await context.bot.send_message(chat_id=chat_id, text=message)

        # user message
        if update:
            # we want to skip this message if the error wasn't triggered by
            #   an update
            chat_id = update.effective_chat.id
            message = (
                "_Oh h*ck, the bot is doing a splish splosh_ \n" "*Please try again*"
            )

            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=constants.ParseMode.MARKDOWN
            )

        # logs to file
        logging.error(f"Update {update} caused error {context.error}")


def main():
    """Start main function, setups logger and starts the bot."""
    # we log everything into the log file
    logging.basicConfig(
        filename=__file__.replace(".py", ".log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        filemode="w",
    )
    # exception tracking
    tracemalloc.start()

    t = Telegram()
    t.start()
    # this line will never be executed as the bot is idling


if __name__ == "__main__":
    main()
