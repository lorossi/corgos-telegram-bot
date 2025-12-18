"""This module contains the entry point of the bot."""

import asyncio
import logging
import tracemalloc
from sys import argv

from modules.telegram import Telegram


async def main(argv: list[str]):
    """Start main function, setups logger and starts the bot."""
    # we log everything into the log file

    if "--debug" in argv:
        level = logging.DEBUG
        filename = None
    else:
        level = logging.WARNING
        filename = __file__.replace(".py", ".log")

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s - %(levelname)s - %(module)s - %(funcName)s "
            "(%(lineno)d) - %(message)s"
        ),
        filemode="w",
        filename=filename,
    )
    # exception tracking
    tracemalloc.start()

    t = Telegram()
    await t.start()

    while True:
        try:
            await asyncio.sleep(0.1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            msg = "Received exit signal, stopping the bot..."
            logging.info(msg)
            print(msg)
            break

    await t.stop()


if __name__ == "__main__":
    asyncio.run(main(argv))
