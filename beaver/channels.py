import json
import sqlite3
import time
from typing import Any, Iterator


class ChannelManager(Iterator):
    """
    A synchronous, blocking iterator that polls a channel for new messages.
    """

    def __init__(
        self, conn: sqlite3.Connection, channel_name: str, poll_interval: float = 0.1
    ):
        """
        Initializes the synchronous subscriber.

        Args:
            conn: The SQLite database connection.
            channel_name: The name of the channel to subscribe to.
            poll_interval: The time in seconds to wait between polling for new messages.
        """
        self._conn = conn
        self._channel = channel_name
        self._poll_interval = poll_interval
        self._last_seen_timestamp = time.time()

    def __iter__(self) -> "ChannelManager":
        """Returns the iterator object itself."""
        return self

    def __next__(self) -> Any:
        """
        Blocks until a new message is available on the channel and returns it.
        This polling mechanism is simple but can introduce a slight latency
        equivalent to the poll_interval.
        """
        while True:
            # Fetch the next available message from the database
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT timestamp, message_payload FROM beaver_pubsub_log WHERE channel_name = ? AND timestamp > ? ORDER BY timestamp ASC LIMIT 1",
                (self._channel, self._last_seen_timestamp),
            )
            result = cursor.fetchone()
            cursor.close()

            if result:
                # If a message is found, update the timestamp and return the payload
                self._last_seen_timestamp = result["timestamp"]
                return json.loads(result["message_payload"])
            else:
                # If no new messages, wait for the poll interval before trying again
                time.sleep(self._poll_interval)
