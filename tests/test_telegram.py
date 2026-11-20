"""This module contains unit tests for the telegram module."""

import shutil
import tempfile
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from telegram.constants import MessageLimit
from telegram.error import Forbidden

from corgos_telegram_bot.modules.settings import Settings, SingletonMeta
from corgos_telegram_bot.modules.telegram import Telegram


class TestTelegramModule(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Telegram module."""

    async def asyncSetUp(self) -> None:
        """Copy the settings to a temporary folder."""
        SingletonMeta._instances.clear()
        self.temp_dir = tempfile.mkdtemp()
        self.settings_path = str(Path(self.temp_dir) / "settings.json")
        shutil.copy("tests/data/telegram_unit_test_settings.json", self.settings_path)

    async def asyncTearDown(self) -> None:
        """Remove the temporary folder."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        SingletonMeta._instances.clear()

    @staticmethod
    @contextmanager
    def mockTelegramDependencies() -> Generator[tuple[MagicMock, Mock]]:
        """Mock dependencies for the Telegram module.

        Yields:
            tuple[MagicMock, Mock]: the mocked application and reddit
        """
        with (
            patch("telegram.ext.Application.builder") as mock_builder,
            patch(
                "corgos_telegram_bot.modules.reddit.asyncpraw.Reddit",
                new_callable=Mock(),
            ) as mock_reddit,
        ):
            mock_app_builder = MagicMock()

            mock_updater = AsyncMock()
            mock_updater.start_polling = AsyncMock()

            mock_telegram = MagicMock()
            mock_telegram.initialize = AsyncMock()
            mock_telegram.start = AsyncMock()
            mock_telegram.stop = AsyncMock()
            mock_telegram.shutdown = AsyncMock()
            mock_telegram.updater = mock_updater
            mock_telegram.bot = AsyncMock()
            mock_telegram.bot.username = "corgos_bot"

            mock_builder.return_value = mock_app_builder

            mock_app_builder.token.return_value = mock_app_builder
            mock_app_builder.build.return_value = mock_telegram

            mock_reddit.return_value = AsyncMock()

            yield mock_telegram, mock_reddit

    async def startedTelegram(self) -> Telegram:
        """Return a Telegram instance with loaded settings and a mocked bot.

        Returns:
            Telegram: the instance
        """
        telegram = Telegram(settings_path=self.settings_path)
        telegram._settings = Settings(settings_path=self.settings_path)
        await telegram._settings.load()
        telegram._application = MagicMock()
        telegram._application.bot = AsyncMock()
        telegram._bot_username = "@corgos_bot"
        return telegram

    @staticmethod
    def makeUpdate(chat_id: int) -> MagicMock:
        """Create a fake update coming from a chat.

        Returns:
            MagicMock: the fake update
        """
        update = MagicMock()
        update.effective_chat.id = chat_id
        return update

    @staticmethod
    def makeContext(args: list[str] | None = None) -> MagicMock:
        """Create a fake callback context.

        Returns:
            MagicMock: the fake context
        """
        context = MagicMock()
        context.bot = AsyncMock()
        context.args = args
        return context

    async def testInitializeTelegram(self) -> None:
        """Test initializing the Telegram instance."""
        Telegram(settings_path=self.settings_path)

    async def testTelegramStartStop(self) -> None:
        """Test starting and stopping the Telegram instance."""
        telegram = Telegram(settings_path=self.settings_path)
        with self.mockTelegramDependencies():
            await telegram.start()
            self.assertEqual(telegram._bot_username, "@corgos_bot")
            await telegram.stop()

    async def testRequestStop(self) -> None:
        """Test that stop requests are tracked, together with restarts."""
        telegram = Telegram(settings_path=self.settings_path)
        self.assertFalse(telegram.restart_requested)

        telegram.requestStop(restart=True)
        await telegram.waitForStopRequest()
        self.assertTrue(telegram.restart_requested)

    async def testNotifyAdminsSurvivesBlockedAdmin(self) -> None:
        """Test that an unreachable admin does not prevent notifying the others."""
        telegram = await self.startedTelegram()
        await telegram._settings.set("telegram_admins", [1, 2])
        telegram._application.bot.send_message.side_effect = [
            Forbidden("blocked"),
            None,
        ]

        await telegram._notifyAdmins("hello")

        self.assertEqual(telegram._application.bot.send_message.await_count, 2)

    async def testErrorHandlerSplitsLongMessages(self) -> None:
        """Test that long error reports are split to fit in telegram messages."""
        telegram = await self.startedTelegram()
        context = self.makeContext()
        context.error = RuntimeError("x" * (MessageLimit.MAX_TEXT_LENGTH * 2))

        await telegram._errorHandler(None, context)

        for call in telegram._application.bot.send_message.await_args_list:
            self.assertLessEqual(len(call.kwargs["text"]), MessageLimit.MAX_TEXT_LENGTH)

    async def testBanUnban(self) -> None:
        """Test banning and unbanning chats."""
        telegram = await self.startedTelegram()
        admin = self.makeUpdate(123456789)

        await telegram._botBanCommand(admin, self.makeContext(["5", "3", "5"]))
        self.assertEqual(await telegram._settings.get("telegram_banned"), [3, 5])

        # unbanning a chat that is not banned must not fail
        await telegram._botUnbanCommand(admin, self.makeContext(["3", "42"]))
        self.assertEqual(await telegram._settings.get("telegram_banned"), [5])

    async def testBanInvalidChatId(self) -> None:
        """Test that invalid chat ids are reported and nothing is banned."""
        telegram = await self.startedTelegram()
        context = self.makeContext(["not-a-number"])

        await telegram._botBanCommand(self.makeUpdate(123456789), context)

        self.assertEqual(await telegram._settings.get("telegram_banned"), [])
        context.bot.send_message.assert_awaited_once()

    async def testBanNonAdmin(self) -> None:
        """Test that non admins cannot ban chats."""
        telegram = await self.startedTelegram()

        await telegram._botBanCommand(self.makeUpdate(1), self.makeContext(["5"]))

        self.assertEqual(await telegram._settings.get("telegram_banned"), [])

    async def testCorgoEmptyQueue(self) -> None:
        """Test that an empty queue schedules a new load."""
        telegram = await self.startedTelegram()
        telegram._jobqueue = MagicMock()
        context = self.makeContext()

        await telegram._botCorgoCommand(self.makeUpdate(1), context)

        context.bot.send_photo.assert_not_awaited()
        telegram._jobqueue.run_once.assert_called_once()

    async def testCorgoSent(self) -> None:
        """Test that a corgo is sent and counted."""
        telegram = await self.startedTelegram()
        telegram._reddit._queue.put_nowait("https://i.redd.it/1.jpg")
        context = self.makeContext()

        with patch("corgos_telegram_bot.modules.telegram.randint", return_value=2):
            await telegram._botCorgoCommand(self.makeUpdate(1), context)

        context.bot.send_photo.assert_awaited_once()
        self.assertEqual(
            context.bot.send_photo.await_args.kwargs["photo"],
            "https://i.redd.it/1.jpg",
        )
        self.assertEqual(await telegram._settings.get("telegram_corgos_sent"), 1)
