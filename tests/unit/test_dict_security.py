import pytest
import os

# Skip all tests in this module if the 'security' extras are not installed.
cryptography = pytest.importorskip("cryptography")

from beaver.security import Cipher, Secret

pytestmark = pytest.mark.unit

# --- Cipher Tests (Encryption) ---


def test_cipher_encrypt_decrypt():
    """Test that data can be encrypted and decrypted successfully."""
    secret = "my-super-secret-key"
    cipher = Cipher(secret)

    original_data = b"This is some sensitive data."

    # 1. Encrypt
    token = cipher.encrypt(original_data)
    assert token != original_data

    # 2. Decrypt
    decrypted_data = cipher.decrypt(token)
    assert decrypted_data == original_data


def test_cipher_invalid_key_fails():
    """Test that decrypting with the wrong secret raises a ValueError."""
    cipher_alice = Cipher("alice-secret")
    cipher_bob = Cipher("bob-secret")

    data = b"Secret Message"
    token = cipher_alice.encrypt(data)

    # Bob tries to decrypt Alice's message
    with pytest.raises(ValueError, match="Invalid secret key"):
        cipher_bob.decrypt(token)


def test_cipher_salt_uniqueness():
    """Test that different salts produce different keys/ciphertexts for the same secret."""
    secret = "shared-secret"

    # Two ciphers with the same secret but different random salts (default behavior)
    c1 = Cipher(secret)
    c2 = Cipher(secret)

    assert c1.salt != c2.salt
    assert c1.key != c2.key

    # Data encrypted by c1 should NOT be decryptable by c2
    # (unless we explicitly shared the salt, which we aren't doing here)
    token = c1.encrypt(b"data")
    with pytest.raises(ValueError):
        c2.decrypt(token)


def test_cipher_deterministic_reconstruction():
    """Test that we can reconstruct a Cipher if we have the secret AND the salt."""
    secret = "persistent-secret"

    # 1. Create original cipher
    c1 = Cipher(secret)
    token = c1.encrypt(b"persist-me")

    # 2. Re-create cipher using the SAME salt
    c2 = Cipher(secret, salt=c1.salt)

    # 3. Verify keys match and decryption works
    assert c1.key == c2.key
    assert c2.decrypt(token) == b"persist-me"


# --- Secret Tests (Hashing) ---


def test_secret_hashing_and_verification():
    """Test that a Secret correctly hashes a password and verifies it."""
    password = "correct-horse-battery-staple"

    # 1. Create secret (hashes immediately)
    secret = Secret(password)

    # Internal state check - ensure they are strings now
    assert isinstance(secret.hash, str)
    assert isinstance(secret.salt, str)
    assert secret.hash != password

    # 2. Verify equality with string
    assert secret == password

    # 3. Verify inequality
    assert secret != "wrong-password"
    assert secret != "Correct-Horse-Battery-Staple"  # Case sensitivity


def test_secret_pydantic_serialization():
    """Test that Secret can be serialized/deserialized by Pydantic/DictManager."""
    password = "my-password"
    original = Secret(password)

    # Simulate dumping to JSON (model_dump in Pydantic v2)
    # This is what DictManager will store in the DB
    dumped_data = original.model_dump()

    assert "hash" in dumped_data
    assert "salt" in dumped_data
    # Verify they are stored as strings
    assert isinstance(dumped_data["hash"], str)
    assert isinstance(dumped_data["salt"], str)

    # Simulate loading from DB
    reloaded = Secret(**dumped_data)

    # Verify the reloaded object works
    assert reloaded == password
    assert reloaded == original
    assert reloaded.hash == original.hash
    assert reloaded.salt == original.salt


def test_secret_salt_randomness():
    """Test that two Secrets created with the same password have different salts/hashes."""
    password = "same-password"

    s1 = Secret(password)
    s2 = Secret(password)

    # They represent the same password...
    assert s1 == password
    assert s2 == password

    # ...but their internal storage should be different (salted)
    assert s1.salt != s2.salt
    assert s1.hash != s2.hash
