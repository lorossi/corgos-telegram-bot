"""This module contains the entry point of the bot."""

import argparse
import asyncio
import logging
import os
import signal
import sys
import tracemalloc

from corgos_telegram_bot.modules.telegram import Telegram

logger = logging.getLogger(__name__)


def parseArgs(argv: list[str]) -> argparse.Namespace:
    """Parse the command line arguments.

    Args:
        argv (list[str]): command line arguments, without the program name

    Returns:
        argparse.Namespace: parsed arguments
    """
    parser = argparse.ArgumentParser(description="Corgos Telegram bot")
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    parser.add_argument(
        "--settings",
        default="settings.json",
        help="path to the settings file (default: %(default)s)",
    )
    return parser.parse_args(argv)


async def main(args: argparse.Namespace) -> bool:
    """Start main function, setups logger and starts the bot.

    Args:
        args (argparse.Namespace): parsed command line arguments

    Returns:
        bool: True if the bot must be restarted, False otherwise
    """
    # setup logger
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format=(
            "%(asctime)s - %(levelname)s - %(module)s - %(funcName)s "
            "(%(lineno)d) - %(message)s"
        ),
    )
    # exception tracking
    tracemalloc.start()

    # start the bot
    t = Telegram(settings_path=args.settings)
    await t.start()

    # stop the bot gracefully on ctrl+c and when the container is stopped
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, t.requestStop)

    try:
        await t.waitForStopRequest()
        logger.info("Received exit signal, stopping the bot...")
    finally:
        await t.stop()

    return t.restart_requested


def run() -> None:
    """Run the bot, restarting the whole process if requested."""
    args = parseArgs(sys.argv[1:])
    if asyncio.run(main(args)):
        logger.warning("Restarting the bot...")
        # replace the current process with a fresh one, same arguments
        # ruff: ignore[start-process-with-no-shell]
        os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    run()
