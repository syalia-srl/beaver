import os
import uuid
import pytest
import asyncio
from beaver.core import BeaverDB, AsyncBeaverDB


@pytest.fixture
def db_path():
    """
    A fixture that creates a unique, temporary database file path
    for each test function, and cleans it up afterward.
    """
    # Create a unique filename for the test database
    db_file = f"test_{uuid.uuid4().hex}.db"

    # Yield the path to the test
    yield db_file

    # Teardown: Clean up the database file after the test runs
    if os.path.exists(db_file):
        os.remove(db_file)


# --- SYNC FIXTURES ---


@pytest.fixture
def db(db_path):
    """
    File-based synchronous BeaverDB.
    """
    db_instance = BeaverDB(db_path)
    yield db_instance
    db_instance.close()


@pytest.fixture
def db_mem():
    """
    In-memory synchronous BeaverDB.
    Fastest option for logic tests that don't check persistence.
    """
    db_instance = BeaverDB(":memory:")
    yield db_instance
    db_instance.close()


@pytest.fixture
def db_cached(db_path):
    """
    File-based synchronous BeaverDB with caching enabled.
    """
    db_instance = BeaverDB(db_path, cache_timeout=0.1)
    yield db_instance
    db_instance.close()


# --- ASYNC FIXTURES ---


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def async_db(db_path):
    """
    File-based AsyncBeaverDB.
    Use this for tests that verify disk persistence or file locking.
    """
    db = AsyncBeaverDB(db_path)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
async def async_db_mem():
    """
    In-memory AsyncBeaverDB.
    Use this for the majority of unit tests (Locks, Dicts, Lists) for maximum speed.
    """
    db = AsyncBeaverDB(":memory:")
    await db.connect()
    yield db
    await db.close()
