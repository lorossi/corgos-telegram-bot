"""This module contains the entry point of the bot."""

import asyncio
import logging
import tracemalloc
from sys import argv

from modules.telegram import Telegram


async def main(argv: list[str]) -> None:
    """Start main function, setups logger and starts the bot."""
    # setup logger
    if "--debug" in argv:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s - %(levelname)s - %(module)s - %(funcName)s "
            "(%(lineno)d) - %(message)s"
        ),
    )
    # exception tracking
    tracemalloc.start()

    # start the bot
    t = Telegram()
    await t.start()

    while True:
        try:
            await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            msg = "Received exit signal, stopping the bot..."
            logging.info(msg)
            print(msg)
            break

    await t.stop()


if __name__ == "__main__":
    asyncio.run(main(argv))
