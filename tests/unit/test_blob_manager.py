from pydantic import BaseModel
import pytest
import base64
from beaver import BeaverDB
from beaver.blobs import Blob

pytestmark = pytest.mark.unit

# --- Test Model for Serialization ---
class FileMeta(BaseModel):
    mimetype: str
    user_id: int

# --- Test Data ---
BLOB_DATA_1 = b"This is a test blob."
BLOB_DATA_2 = b"\x00\x01\x02\x03\x04"

# --- Test Cases ---

# 1. Basic Operations

def test_blob_put_and_get(db_memory: BeaverDB):
    """Tests basic put and get operations."""
    blobs = db_memory.blob("test_put_get")

    blobs.put("key1", BLOB_DATA_1)

    blob = blobs.get("key1")

    assert blob is not None
    assert isinstance(blob, Blob)
    assert blob.key == "key1"
    assert blob.data == BLOB_DATA_1
    assert blob.metadata is None

def test_blob_put_with_metadata(db_memory: BeaverDB):
    """Tests storing and retrieving a blob with metadata."""
    blobs = db_memory.blob("test_metadata")
    metadata = {"mimetype": "text/plain", "size": len(BLOB_DATA_1)}

    blobs.put("key1", BLOB_DATA_1, metadata=metadata)

    blob = blobs.get("key1")

    assert blob is not None
    assert blob.data == BLOB_DATA_1
    assert blob.metadata == metadata

def test_blob_put_overwrite(db_memory: BeaverDB):
    """Tests that putting a blob with an existing key overwrites it."""
    blobs = db_memory.blob("test_overwrite")

    blobs.put("key1", BLOB_DATA_1, metadata={"version": 1})
    blob_v1 = blobs.get("key1")
    assert blob_v1.data == BLOB_DATA_1
    assert blob_v1.metadata == {"version": 1}

    blobs.put("key1", BLOB_DATA_2, metadata={"version": 2})
    blob_v2 = blobs.get("key1")
    assert blob_v2.data == BLOB_DATA_2
    assert blob_v2.metadata == {"version": 2}

    assert len(blobs) == 1

def test_blob_put_invalid_data_type(db_memory: BeaverDB):
    """Tests that put() raises TypeError for non-bytes data."""
    blobs = db_memory.blob("test_invalid_data")
    with pytest.raises(TypeError):
        blobs.put("key1", "this is a string, not bytes")

def test_blob_get_not_found(db_memory: BeaverDB):
    """Tests that get() returns None for a missing key."""
    blobs = db_memory.blob("test_get_not_found")
    assert blobs.get("missing_key") is None

def test_blob_delete(db_memory: BeaverDB):
    """Tests the delete() method."""
    blobs = db_memory.blob("test_delete")
    blobs.put("key1", BLOB_DATA_1)

    assert len(blobs) == 1

    blobs.delete("key1")

    assert len(blobs) == 0
    assert blobs.get("key1") is None

def test_blob_delete_not_found(db_memory: BeaverDB):
    """Tests that delete() raises KeyError for a missing key."""
    blobs = db_memory.blob("test_delete_not_found")

    with pytest.raises(KeyError):
        blobs.delete("missing_key")

# 2. Pythonic Dunder Methods

def test_blob_contains(db_memory: BeaverDB):
    """Tests the __contains__ (in) operator."""
    blobs = db_memory.blob("test_contains")
    blobs.put("key1", BLOB_DATA_1)

    assert "key1" in blobs
    assert "missing_key" not in blobs

def test_blob_len_and_iter(db_memory: BeaverDB):
    """Tests __len__ and __iter__ (which yields keys)."""
    blobs = db_memory.blob("test_len_iter")

    assert len(blobs) == 0
    assert list(blobs) == []

    blobs.put("key1", BLOB_DATA_1)
    blobs.put("key2", BLOB_DATA_2)

    assert len(blobs) == 2

    keys = list(blobs)
    assert len(keys) == 2
    assert "key1" in keys
    assert "key2" in keys

# 3. Advanced Features (Serialization & Dump)

def test_blob_with_model_serialization(db_memory: BeaverDB):
    """Tests that metadata is correctly serialized/deserialized with a model."""
    blobs = db_memory.blob("test_model", model=FileMeta)

    meta_obj = FileMeta(mimetype="image/png", user_id=123)
    blobs.put("avatar.png", BLOB_DATA_1, metadata=meta_obj)

    blob = blobs.get("avatar.png")

    assert blob is not None
    assert isinstance(blob.metadata, FileMeta)
    assert blob.metadata.mimetype == "image/png"
    assert blob.metadata.user_id == 123

def test_blob_dump(db_memory: BeaverDB):
    """Tests the .dump() method, including base64 encoding."""
    blobs = db_memory.blob("test_dump")
    metadata = {"mimetype": "text/plain"}

    blobs.put("file.txt", BLOB_DATA_1, metadata=metadata)

    dump_data = blobs.dump()

    assert dump_data["metadata"]["type"] == "BlobStore"
    assert dump_data["metadata"]["name"] == "test_dump"
    assert dump_data["metadata"]["count"] == 1

    items = dump_data["items"]
    assert len(items) == 1

    item = items[0]
    assert item["key"] == "file.txt"
    assert item["metadata"] == metadata

    # Check that data was correctly base64 encoded
    assert item["data_b64"] == base64.b64encode(BLOB_DATA_1).decode('utf-8')

    # Check that we can decode it back
    assert base64.b64decode(item["data_b64"]) == BLOB_DATA_1
