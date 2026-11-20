"""A module to manage Reddit settings using a singleton pattern."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
from typing import TYPE_CHECKING, Any, ClassVar

import aiofiles
import aiofiles.os
import ujson

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_SETTINGS_PATH = "settings.json"

logger = logging.getLogger(__name__)


class SingletonMeta(type):
    """A metaclass for creating singleton classes, one per settings path."""

    _instances: ClassVar[dict[tuple[type, str], Settings]] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Settings:
        """Return the singleton instance of the class."""
        if "settings_path" not in kwargs:
            kwargs["settings_path"] = args[0] if args else DEFAULT_SETTINGS_PATH
            args = args[1:]

        key_tuple = (cls, kwargs["settings_path"])
        if key_tuple not in cls._instances:
            logger.debug("Creating new instance of singleton class %s", cls.__name__)
            instance = super().__call__(*args, **kwargs)
            cls._instances[key_tuple] = instance

        return cls._instances[key_tuple]


class Settings(metaclass=SingletonMeta):
    """A singleton class to manage settings."""

    _data_lock: asyncio.Lock
    _settings: dict[str, Any]

    def __init__(self: Settings, settings_path: str = DEFAULT_SETTINGS_PATH) -> None:
        """Initialize the Settings with the path to the settings file."""
        self._path = settings_path

        self._data_lock = asyncio.Lock()
        self._settings = {}

    async def load(self: Settings) -> None:
        """Load settings from a JSON file."""
        logger.debug("Loading settings from %s", self._path)
        async with self._data_lock, aiofiles.open(self._path) as f:
            content = await f.read()
            self._settings = ujson.loads(content)
        logger.debug("Settings loaded from %s", self._path)

    async def validate(self: Settings, required_keys: list[str]) -> None:
        """Validate that all required keys are present in the settings.

        Args:
            required_keys (list[str]): A list of keys that must be present
                in the settings.

        Raises:
            KeyError: If any required key is missing from the settings.
        """
        logger.debug("Validating settings with required keys: %s", required_keys)
        async with self._data_lock:
            for key in required_keys:
                if key not in self._settings:
                    error_msg = f"Required key '{key}' not found in settings."
                    logger.error(error_msg)
                    raise KeyError(error_msg)

        logger.debug("All required keys are present in the settings")

    async def _saveNoLock(self: Settings) -> None:
        """Save settings to a JSON file without acquiring the lock.

        The settings are first written to a temporary file which then
        atomically replaces the old one, so a crash cannot leave a
        truncated settings file behind.
        """
        logger.debug("Saving settings to %s without lock", self._path)
        temp_path = f"{self._path}.tmp"
        async with aiofiles.open(temp_path, mode="w") as f:
            await f.write(ujson.dumps(self._settings, indent=4))
            await f.flush()
            await asyncio.to_thread(os.fsync, f.fileno())
        await aiofiles.os.replace(temp_path, self._path)
        logger.debug("Settings saved without lock")

    async def save(self: Settings) -> None:
        """Save settings to a JSON file."""
        logger.debug("Saving settings to %s", self._path)
        async with self._data_lock:
            await self._saveNoLock()
        logger.debug("Settings saved")

    async def to_dict(self: Settings) -> dict[str, Any]:
        """Return a copy of the settings as a dictionary."""
        logger.debug("Returning settings as dictionary")
        async with self._data_lock:
            return copy.deepcopy(self._settings)

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
        logger.debug("Setting key '%s' to value '%s'", key, value)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logger.error(error_msg)
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
        """Get a copy of a specific setting.

        Args:
            key (str): The setting key to get.
            deserializer (Callable[[Any], Any] | None): Optional function to deserialize
                the value before returning it.

        Returns:
            Any: The value of the setting.

        Raises:
            KeyError: If the key does not exist in the settings.
        """
        logger.debug("Getting value for key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logger.error(error_msg)
                raise KeyError(error_msg)

            value = copy.deepcopy(self._settings[key])

        if deserializer:
            return deserializer(value)
        return value

    async def apply(self: Settings, key: str, func: Callable[[Any], Any]) -> Any:
        """Apply a function to a specific setting.

        Args:
            key (str): The setting key to apply the function to.
            func (Callable[[Any], Any]): The function to apply to the setting value.

        Returns:
            Any: The updated value of the setting.

        Raises:
            KeyError: If the key does not exist in the settings.
        """
        logger.debug("Applying function to key '%s'", key)
        async with self._data_lock:
            if key not in self._settings:
                error_msg = f"Key '{key}' not found in settings."
                logger.error(error_msg)
                raise KeyError(error_msg)

            self._settings[key] = func(self._settings[key])
            await self._saveNoLock()
            return copy.deepcopy(self._settings[key])
