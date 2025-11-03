import os
import uuid
import pytest
from beaver import BeaverDB

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

@pytest.fixture
def db(db_path):
    """
    A fixture that provides an initialized BeaverDB instance
    using the temporary db_path. It ensures the database
    is properly closed after the test.
    """
    # Setup: Initialize the database
    db_instance = BeaverDB(db_path)

    # Yield the instance to the test
    yield db_instance

    # Teardown: Close the database connection
    db_instance.close()


@pytest.fixture
def db_memory(db_path):
    """
    A fixture that provides an initialized BeaverDB instance
    using the temporary db_path. It ensures the database
    is properly closed after the test.
    """
    # Setup: Initialize the database
    db_instance = BeaverDB(":memory:")

    # Yield the instance to the test
    yield db_instance

    # Teardown: Close the database connection
    db_instance.close()