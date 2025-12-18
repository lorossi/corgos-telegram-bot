"""A module to manage Reddit settings using a singleton pattern."""

import asyncio
import logging
from typing import Any, Callable

import aiofiles
import ujson


class SingletonMeta(type):
    """A metaclass for creating singleton classes."""

    _instances: dict = {}

    def __call__(cls, *args, **kwargs) -> object:
        """Return the singleton instance of the class."""
        if cls not in cls._instances:
            logging.debug("Creating new instance of singleton class %s", cls.__name__)
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class Settings(metaclass=SingletonMeta):
    """A singleton class to manage settings."""

    _data_lock: asyncio.Lock
    _settings: dict[str, int | str | list[int]]

    def __init__(self, path: str = "settings.json") -> None:
        """Initialize the Settings with the path to the settings file."""
        self._path = path

        self._data_lock = asyncio.Lock()
        self._settings = {}

    async def load(self) -> None:
        """Load settings from a JSON file."""
        logging.debug("Loading settings from %s", self._path)
        await self._data_lock.acquire()
        async with aiofiles.open(self._path, mode="r") as f:
            content = await f.read()
            self._settings = ujson.loads(content)
        self._data_lock.release()
        logging.debug("Settings loaded: %s", self._settings)

    async def _saveNoLock(self) -> None:
        """Save settings to a JSON file without acquiring the lock."""
        logging.debug("Saving settings to %s without lock", self._path)
        async with aiofiles.open(self._path, mode="w") as f:
            settings_str = ujson.dumps(self._settings, indent=4)
            await f.write(settings_str)
        logging.debug("Settings saved without lock")

    async def save(self) -> None:
        """Save settings to a JSON file."""
        logging.debug("Saving settings to %s", self._path)
        async with self._data_lock:
            await self._saveNoLock()
        logging.debug("Settings saved")

    async def to_dict(self) -> dict:
        """Return the settings as a dictionary."""
        logging.debug("Returning settings as dictionary")
        async with self._data_lock:
            return self._settings

    async def set(
        self,
        key: str,
        value,
        serializer: Callable[[Any], Any] | None = None,
    ) -> None:
        """Set a specific setting."""
        logging.debug("Setting key '%s' to value '%s'", key, value)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logging.error(error_msg)
                raise KeyError(error_msg)

            if serializer:
                self._settings[key] = serializer(value)
            else:
                self._settings[key] = value

            await self._saveNoLock()

    async def get(
        self, key: str, deserializer: Callable[[Any], Any] | None = None
    ) -> Any:
        """Get a specific setting."""
        logging.debug("Getting value for key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logging.error(error_msg)
                raise KeyError(error_msg)

            if deserializer:
                return deserializer(self._settings[key])
            return self._settings[key]

    async def apply(self, key: str, func: Callable[[Any], Any]) -> None:
        """Apply a function to a specific setting."""
        logging.debug("Applying function to key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logging.error(error_msg)
                raise KeyError(error_msg)

            self._settings[key] = func(self._settings[key])
            await self._saveNoLock()
            return self._settings[key]
