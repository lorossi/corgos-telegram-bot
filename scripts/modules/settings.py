"""A module to manage Reddit settings using a singleton pattern."""

import asyncio
from typing import Any, Callable

import aiofiles
import ujson


class SingletonMeta(type):
    """A metaclass for creating singleton classes."""

    _instances: dict = {}

    def __call__(cls, *args, **kwargs) -> object:
        """Return the singleton instance of the class."""
        if cls not in cls._instances:
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
        await self._data_lock.acquire()
        async with aiofiles.open(self._path, mode="r") as f:
            content = await f.read()
            self._settings = ujson.loads(content)
        self._data_lock.release()

    async def _saveNoLock(self) -> None:
        """Save settings to a JSON file without acquiring the lock."""
        async with aiofiles.open(self._path, mode="w") as f:
            settings_str = ujson.dumps(self._settings, indent=4)
            await f.write(settings_str)

    async def save(self) -> None:
        """Save settings to a JSON file."""
        async with self._data_lock:
            await self._saveNoLock()

    async def to_dict(self) -> dict:
        """Return the settings as a dictionary."""
        async with self._data_lock:
            return self._settings

    async def set(
        self,
        key: str,
        value,
        serializer: Callable[[Any], Any] | None = None,
    ) -> None:
        """Set a specific setting."""
        async with self._data_lock:
            if key not in self._settings:
                raise KeyError(f"Key '{key}' not found in settings.")

            if serializer:
                self._settings[key] = serializer(value)
            else:
                self._settings[key] = value

            await self._saveNoLock()

    async def get(
        self, key: str, deserializer: Callable[[Any], Any] | None = None
    ) -> Any:
        """Get a specific setting."""
        async with self._data_lock:
            if key not in self._settings:
                raise KeyError(f"Key '{key}' not found in settings.")

            if deserializer:
                return deserializer(self._settings[key])
            return self._settings[key]

    async def apply(self, key: str, func: Callable[[Any], Any]) -> None:
        """Apply a function to a specific setting."""
        async with self._data_lock:
            if key not in self._settings:
                raise KeyError(f"Key '{key}' not found in settings.")

            self._settings[key] = func(self._settings[key])
            await self._saveNoLock()
            return self._settings[key]
