# examples/textual_chat.py
#
# To run this example, you first need to install textual:
# pip install textual

import sys
import threading
import time
import uuid
from datetime import datetime

from beaver import BeaverDB

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Input, ListView, ListItem, Label, Static
from textual.message import Message


# --- 1. Configuration ---

DB_PATH = "chat.db"
HEARTBEAT_INTERVAL_SECONDS = 5
USER_TTL_SECONDS = 15  # A user is considered offline after 15 seconds

# --- 2. Custom Textual Messages for UI updates ---


class NewLogMessage(Message):
    """A message to add a new log/chat entry to the UI."""

    def __init__(self, text: str, style: str) -> None:
        self.text = text
        self.style = style
        super().__init__()


class UpdateUserList(Message):
    """A message to refresh the online user list in the UI."""

    def __init__(self, users: list[str]) -> None:
        self.users = users
        super().__init__()


# --- 3. BeaverDB Chat Client (The "Backend") ---


class ChatClient:
    """
    Handles all the backend logic and communication with BeaverDB.
    It runs in the background and communicates with the TUI via Textual messages.
    """

    def __init__(self, app: App, room_name: str, username: str):
        self.app = app
        self.room_name = room_name
        self.username = username
        self.db = BeaverDB(DB_PATH)
        self.stop_event = threading.Event()

        # BeaverDB feature usage
        self.events_channel = self.db.channel(f"chat_{room_name}_events")
        self.online_users = self.db.dict(f"chat_{room_name}_online_users")
        self.message_history = self.db.list(f"chat_{room_name}_history")

    def _publish_event(self, event_type: str, data: dict):
        """Helper to publish a structured event to the channel."""
        payload = {"type": event_type, "user": self.username, **data}
        self.events_channel.publish(payload)

    def _listener_thread_task(self):
        """
        Background thread that listens for new events from the BeaverDB channel
        and posts messages to the Textual app to update the UI.
        """
        with self.events_channel.subscribe() as listener:
            while not self.stop_event.is_set():
                try:
                    for message in listener.listen(timeout=1):
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        log_msg = ""
                        style = ""

                        if message["type"] == "join":
                            if message["user"] != self.username:
                                log_msg = f"{timestamp} [SYSTEM] -> {message['user']} has joined the room."
                                style = "italic green"
                        elif message["type"] == "leave":
                            if message["user"] != self.username:
                                log_msg = f"{timestamp} [SYSTEM] -> {message['user']} has left the room."
                                style = "italic yellow"
                        elif message["type"] == "message":
                            sender = (
                                "You"
                                if message["user"] == self.username
                                else message["user"]
                            )
                            log_msg = f"{timestamp} [{sender}] -> {message['text']}"
                            style = "bold magenta" if sender == "You" else ""

                        if log_msg:
                            # IMPORTANT: Use call_from_thread to safely update the TUI
                            self.app.call_from_thread(
                                self.app.post_message, NewLogMessage(log_msg, style)
                            )
                except TimeoutError:
                    continue

    def start(self):
        """Initializes the client and starts the background listener."""
        self._publish_event("join", {})
        threading.Thread(target=self._listener_thread_task, daemon=True).start()
        # Post history to UI
        history = self.message_history[-10:]
        if history:
            self.app.post_message(
                NewLogMessage("--- Last 10 messages ---", "bold blue")
            )
            for msg in history:
                log_msg = f"[{msg['user']}] -> {msg['text']}"
                self.app.post_message(NewLogMessage(log_msg, []))
            self.app.post_message(
                NewLogMessage("------------------------", "bold blue")
            )

    def stop(self):
        """Stops the client and cleans up resources."""
        self.stop_event.set()
        self._publish_event("leave", {})
        if self.username in self.online_users:
            del self.online_users[self.username]
        self.db.close()

    def send_message(self, text: str):
        """Sends a message to the channel and saves it to history."""
        self._publish_event("message", {"text": text})
        self.message_history.push({"user": self.username, "text": text})

    def send_heartbeat(self):
        """Refreshes this user's TTL in the online user list."""
        self.online_users.set(
            self.username, {"status": "online"}, ttl_seconds=USER_TTL_SECONDS
        )

    def refresh_online_users(self):
        """Gets the current user list and posts an update to the UI."""
        users = list(self.online_users.keys())
        self.app.post_message(UpdateUserList(users))


# --- 4. The Textual TUI Application ---


class ChatApp(App):
    """A Textual TUI for the BeaverDB distributed chat."""

    CSS_PATH = "textual_chat.css"
    TITLE = "BeaverDB Distributed Chat"

    def __init__(self, room_name: str, username: str):
        self.room_name = room_name
        self.username = username
        self.chat_client = ChatClient(self, self.room_name, self.username)
        super().__init__()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Container(
            Static(f"Room: {self.room_name}", id="room-title"),
            Horizontal(
                ListView(id="messages"),
                Container(
                    Static("ONLINE USERS", classes="sidebar-title"),
                    Static(id="user-list", classes="sidebar-content"),
                    id="sidebar",
                ),
            ),
            Input(
                placeholder="Type your message and press Enter...", id="message-input"
            ),
            id="app-grid",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.query_one("#message-input", Input).focus()
        self.chat_client.start()
        # Set timers to periodically send heartbeats and refresh the user list
        self.set_interval(HEARTBEAT_INTERVAL_SECONDS, self.chat_client.send_heartbeat)
        self.set_interval(
            HEARTBEAT_INTERVAL_SECONDS / 2, self.chat_client.refresh_online_users
        )

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle the user pressing Enter in the input box."""
        if message.value:
            self.chat_client.send_message(message.value)
            self.query_one("#message-input", Input).value = ""

    def on_new_log_message(self, message: NewLogMessage) -> None:
        """Handle a new chat/log message from the backend client."""
        log_view = self.query_one("#messages", ListView)
        list_item = ListItem(Label(message.text))
        list_item.styles.color = (
            message.style.split(" ")[-1] if message.style else "white"
        )
        if "italic" in message.style:
            list_item.styles.text_style = "italic"
        if "bold" in message.style:
            list_item.styles.text_style = "bold"
        # if "dim" in message.style:
        #     list_item.styles.text_style = "dim"
        log_view.append(list_item)
        log_view.scroll_end()

    def on_update_user_list(self, message: UpdateUserList) -> None:
        """Handle a user list refresh from the backend client."""
        user_list_widget = self.query_one("#user-list", Static)
        user_list_content = "\n".join(f"- {user}" for user in sorted(message.users))
        user_list_widget.update(user_list_content)

    def on_unmount(self) -> None:
        """Called when the app is unmounted."""
        self.chat_client.stop()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python textual_chat.py <room> <user>")
        sys.exit(1)

    room = sys.argv[1]
    user = sys.argv[2]

    app = ChatApp(room_name=room, username=user)
    app.run()
