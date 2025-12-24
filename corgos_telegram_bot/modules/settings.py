"""A module to manage Reddit settings using a singleton pattern."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiofiles
import ujson


class SingletonMeta(type):
    """A metaclass for creating singleton classes."""

    _instances: dict[tuple, Settings] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Settings:
        """Return the singleton instance of the class."""
        if "settings_path" not in kwargs:
            kwargs["settings_path"] = args[0]
            args = args[1:]

        key_tuple = (cls, kwargs["settings_path"])
        if key_tuple not in cls._instances:
            logging.debug("Creating new instance of singleton class %s", cls.__name__)
            instance = super().__call__(*args, **kwargs)
            cls._instances[key_tuple] = instance

        return cls._instances[key_tuple]


class Settings(metaclass=SingletonMeta):
    """A singleton class to manage settings."""

    _data_lock: asyncio.Lock
    _settings: dict[str, int | str | list[int]]

    def __init__(self: Settings, settings_path: str = "settings.json") -> None:
        """Initialize the Settings with the path to the settings file."""
        self._path = settings_path

        self._data_lock = asyncio.Lock()
        self._settings = {}

    async def load(self: Settings) -> None:
        """Load settings from a JSON file."""
        logging.debug("Loading settings from %s", self._path)
        await self._data_lock.acquire()
        async with aiofiles.open(self._path, mode="r") as f:
            content = await f.read()
            self._settings = ujson.loads(content)
        self._data_lock.release()
        logging.debug("Settings loaded: %s", self._settings)

    async def validate(self: Settings, required_keys: list[str]) -> None:
        """Validate that all required keys are present in the settings.

        Args:
            required_keys (list[str]): A list of keys that must be present in the settings.

        Raises:
            KeyError: If any required key is missing from the settings.
        """
        logging.debug("Validating settings with required keys: %s", required_keys)
        async with self._data_lock:
            for key in required_keys:
                if key not in self._settings:
                    error_msg = f"Required key '{key}' not found in settings."
                    logging.error(error_msg)
                    raise KeyError(error_msg)

        logging.debug("All required keys are present in the settings")

    async def _saveNoLock(self: Settings) -> None:
        """Save settings to a JSON file without acquiring the lock."""
        logging.debug("Saving settings to %s without lock", self._path)
        async with aiofiles.open(self._path, mode="w") as f:
            settings_str = ujson.dumps(self._settings, indent=4)
            await f.write(settings_str)
        logging.debug("Settings saved without lock")

    async def save(self: Settings) -> None:
        """Save settings to a JSON file."""
        logging.debug("Saving settings to %s", self._path)
        async with self._data_lock:
            await self._saveNoLock()
        logging.debug("Settings saved")

    async def to_dict(self: Settings) -> dict:
        """Return the settings as a dictionary."""
        logging.debug("Returning settings as dictionary")
        async with self._data_lock:
            return self._settings

    async def set(
        self: Settings,
        key: str,
        value: Any,
        serializer: Callable[[Any], Any] | None = None,
    ) -> None:
        """Set a specific setting.

        Args:
            key (str): The setting key to set.
            value (Any): The value to set for the key.
            serializer (Callable[[Any], Any] | None): Optional function to serialize
                the value before setting it.

        Raises:
            KeyError: If the key does not exist in the settings.
        """
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
        self: Settings,
        key: str,
        deserializer: Callable[[Any], Any] | None = None,
    ) -> Any:
        """Get a specific setting.

        Args:
            key (str): The setting key to get.
            deserializer (Callable[[Any], Any] | None): Optional function to deserialize
                the value before returning it.

        Raises:
            KeyError: If the key does not exist in the settings.

        Returns:
            Any: The value of the setting.
        """
        logging.debug("Getting value for key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logging.error(error_msg)
                raise KeyError(error_msg)

            if deserializer:
                return deserializer(self._settings[key])
            return self._settings[key]

    async def apply(
        self: Settings, key: str, func: Callable[[Any], Any]
    ) -> int | str | list[int]:
        """Apply a function to a specific setting.

        Args:
            key (str): The setting key to apply the function to.
            func (Callable[[Any], Any]): The function to apply to the setting value.

        Raises:
            KeyError: If the key does not exist in the settings.

        Returns:
            int | str | list[int]: The updated value of the setting.
        """
        logging.debug("Applying function to key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logging.error(error_msg)
                raise KeyError(error_msg)

            self._settings[key] = func(self._settings[key])
            await self._saveNoLock()
            return self._settings[key]
