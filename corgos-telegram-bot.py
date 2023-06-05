import logging
import tracemalloc
from sys import argv

from modules.telegram import Telegram


def main(argv: list[str]):
    """Start main function, setups logger and starts the bot."""
    # we log everything into the log file

    if "--debug" in argv:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    logging.basicConfig(
        filename=__file__.replace(".py", ".log"),
        level=level,
        format=(
            "%(asctime)s - %(levelname)s - %(module)s - %(funcName)s "
            "(%(lineno)d) - %(message)s"
        ),
        filemode="w",
    )
    # exception tracking
    tracemalloc.start()

    t = Telegram()
    t.start()
    # this line will never be executed as the bot is idling


if __name__ == "__main__":
    main(argv)
