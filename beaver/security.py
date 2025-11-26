import base64
import os
from typing import Any, Optional

from pydantic import BaseModel

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
except ImportError:
    # We define dummy classes or raise errors if accessed without dependencies
    Fernet = None  # type: ignore

    def require_security():
        raise ImportError(
            'The "security" extra is required to use this feature. '
            'Please install it with: pip install "beaver-db[security]"'
        )

else:

    def require_security():
        pass


class Cipher:
    """
    Handles symmetric encryption using Fernet (AES-128 CBC + HMAC-SHA256).
    Used by Encrypted Dictionaries to secure values at rest.
    """

    def __init__(self, secret: str, salt: bytes | None = None):
        require_security()
        if not salt:
            salt = os.urandom(16)
        self.salt = salt
        self.key = self._derive_key(secret, salt)
        self.fernet = Fernet(self.key)

    @staticmethod
    def _derive_key(secret: str, salt: bytes) -> bytes:
        """Derives a 32-byte, url-safe base64 key from the secret using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
            backend=default_backend(),
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

    def encrypt(self, data: bytes) -> bytes:
        """Encrypts bytes."""
        return self.fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        """Decrypts bytes. Raises ValueError if the key is incorrect."""
        try:
            return self.fernet.decrypt(token)
        except InvalidToken:
            raise ValueError("Invalid secret key or corrupted data.")


class Secret(BaseModel):
    """
    A value type for secure, one-way password hashing.
    Stores only the hash and salt as base64 strings, ensuring JSON compatibility.
    """

    hash: str
    salt: str

    def __init__(self, value: str | None = None, **kwargs):
        """
        Can be initialized in two ways:
        1. New Secret: Secret("my-password") -> Hashes and stores it as b64 strings.
        2. Loading:    Secret(hash="...", salt="...") -> Reconstructs it.
        """
        # Ensure security deps are present
        if value is not None or (not kwargs.get("hash")):
            require_security()

        if value is not None:
            # 1. User provided a plain-text password to hash
            salt_bytes = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt_bytes,
                iterations=100_000,
                backend=default_backend(),
            )
            hashed_bytes = kdf.derive(value.encode())

            # Store as base64 strings
            super().__init__(
                hash=base64.b64encode(hashed_bytes).decode("utf-8"),
                salt=base64.b64encode(salt_bytes).decode("utf-8"),
            )
        else:
            # 2. Pydantic is loading from arguments (hash/salt)
            super().__init__(**kwargs)

    def __eq__(self, other: Any) -> bool:
        """
        Checks equality.
        - If comparing to another Secret, checks hash equality.
        - If comparing to a string, checks if the string hashes to the stored value.
        """
        if isinstance(other, Secret):
            return self.hash == other.hash and self.salt == other.salt

        if isinstance(other, str):
            require_security()

            # Decode stored strings back to bytes
            try:
                salt_bytes = base64.b64decode(self.salt)
                hash_bytes = base64.b64decode(self.hash)
            except (ValueError, TypeError):
                return False

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt_bytes,
                iterations=100_000,
                backend=default_backend(),
            )
            try:
                kdf.verify(other.encode(), hash_bytes)
                return True
            except Exception:
                return False

        return False

    def __repr__(self) -> str:
        return f"Secret(hash={self.hash[:8]}...)"

    def __str__(self) -> str:
        return "********"
