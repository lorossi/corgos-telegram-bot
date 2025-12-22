"""This module contains unit tests for the settings module."""

import os
import shutil
import unittest
from typing import Any

import aiofiles
import ujson
from modules.settings import Settings


class TestSettings(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the Settings class."""

    async def asyncSetUp(self) -> None:
        """Set up a temporary settings file before each test."""
        self.temp_dir = "temp_test_settings"
        os.makedirs(self.temp_dir, exist_ok=True)
        self.expected_content = {
            "key1": "value1",
            "key2": 42,
            "key3": [1, 2, 3],
        }

    async def asyncTearDown(self) -> None:
        """Remove the temporary settings file after each test."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def createSettingsFile(
        self, content: dict, filename: str = "settings.json"
    ) -> str:
        """Create a temporary settings file with the given content.

        Args:
            content (dict): The content to write to the settings file.
            filename (str): The name of the settings file.

        Returns:
            str: The path to the created settings file.
        """
        test_path = os.path.join(self.temp_dir, filename)
        async with aiofiles.open(test_path, mode="w") as f:
            await f.write(ujson.dumps(content))

        return test_path

    async def testUnicity(self) -> None:
        """Test that multiple instances of Settings are independent."""
        test_path1 = await self.createSettingsFile(self.expected_content)
        test_path2 = await self.createSettingsFile(self.expected_content)

        settings1 = Settings(path=test_path1)
        settings2 = Settings(path=test_path2)

        await settings1.load()
        await settings2.load()

        self.assertEqual(await settings1.to_dict(), await settings2.to_dict())

        await settings1.set("key1", "new_value1")
        value1 = await settings1.get("key1")
        value2 = await settings2.get("key1")

        self.assertEqual(value1, "new_value1")
        self.assertEqual(value2, "new_value1")

    async def testLoad(self) -> None:
        """Test loading settings from a file."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        self.assertEqual(await settings.to_dict(), self.expected_content)

    async def testSaveLoad(self) -> None:
        """Test saving and loading settings."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        await settings.set("key2", 100)
        await settings.save()
        del settings

        # Reload settings to verify persistence
        new_settings = Settings(path=test_path)
        await new_settings.load()
        value = await new_settings.get("key2")
        self.assertEqual(value, 100)

    async def testSetLoad(self) -> None:
        """Test set (with implicit save) and loading settings."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        await settings.set("key2", 100)
        del settings

        # Reload settings to verify persistence
        new_settings = Settings(path=test_path)
        await new_settings.load()
        value = await new_settings.get("key2")
        self.assertEqual(value, 100)

    async def testGet(self) -> None:
        """Test getting a specific setting."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        value = await settings.get("key2")
        self.assertEqual(value, 42)

    async def testSet(self) -> None:
        """Test setting a specific setting."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        await settings.set("key1", "new_value")
        value = await settings.get("key1")
        self.assertEqual(value, "new_value")

    async def testGetNonExistentKey(self) -> None:
        """Test getting a non-existent key raises KeyError."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        with self.assertRaises(KeyError):
            await settings.get("non_existent_key")

    async def testSetNonExistentKey(self) -> None:
        """Test setting a non-existent key raises KeyError."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        with self.assertRaises(KeyError):
            await settings.set("non_existent_key", "value")

    async def testGetWithDeserializer(self) -> None:
        """Test getting a setting with a deserializer."""
        content = {
            "int_value": "123",
        }
        test_path = await self.createSettingsFile(content)
        settings = Settings(path=test_path)
        await settings.load()

        def deserializer(value: Any) -> int:
            return int(value)

        value = await settings.get("int_value", deserializer=deserializer)
        self.assertEqual(value, 123)

    async def testSetWithSerializer(self) -> None:
        """Test setting a setting with a serializer."""
        content = {
            "int_value": "123",
        }
        test_path = await self.createSettingsFile(content)
        settings = Settings(path=test_path)
        await settings.load()

        def serializer(value: int) -> str:
            return str(value)

        await settings.set("int_value", 456, serializer=serializer)
        value = await settings.get("int_value")
        self.assertEqual(value, "456")

        # load again to verify persistence
        new_settings = Settings(path=test_path)
        await new_settings.load()
        value = await new_settings.get("int_value")
        self.assertEqual(value, "456")

    async def testApply(self) -> None:
        """Test applying a function to a specific setting."""
        content = {
            "counter": 10,
        }
        test_path = await self.createSettingsFile(content)
        settings = Settings(path=test_path)
        await settings.load()

        value = await settings.apply("counter", lambda x: x + 5)
        self.assertEqual(value, 15)
        value = await settings.get("counter")
        self.assertEqual(value, 15)
        del settings

        # load again to verify persistence
        new_settings = Settings(path=test_path)
        await new_settings.load()
        value = await new_settings.get("counter")
        self.assertEqual(value, 15)

    async def testApplyList(self) -> None:
        """Test applying a function to a list setting."""
        content = {
            "numbers": [1, 2, 3],
        }
        test_path = await self.createSettingsFile(content)
        settings = Settings(path=test_path)
        await settings.load()

        def append_number(lst: list[int], number: int) -> list[int]:
            lst.append(number)
            return lst

        def pop_number(lst: list[int]) -> list[int]:
            lst.pop()
            return lst

        def remove_number(lst: list[int], number: int) -> list[int]:
            lst.remove(number)
            return lst

        value = await settings.apply("numbers", lambda x: append_number(x, 4))
        self.assertEqual(value, [1, 2, 3, 4])
        value = await settings.get("numbers")
        self.assertEqual(value, [1, 2, 3, 4])

        value = await settings.apply("numbers", pop_number)
        self.assertEqual(value, [1, 2, 3])
        value = await settings.get("numbers")
        self.assertEqual(value, [1, 2, 3])

        value = await settings.apply("numbers", lambda x: remove_number(x, 2))
        self.assertEqual(value, [1, 3])
        value = await settings.get("numbers")
        self.assertEqual(value, [1, 3])

    async def testApplyNonExistentKey(self) -> None:
        """Test applying a function to a non-existent key raises KeyError."""
        test_path = await self.createSettingsFile(self.expected_content)
        settings = Settings(path=test_path)
        await settings.load()
        with self.assertRaises(KeyError):
            await settings.apply("non_existent_key", lambda x: x)
