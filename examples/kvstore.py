from beaver import BeaverDB


def kv_store_demo():
    """Demonstrates the synchronous get/set functionality."""
    print("--- Running Key-Value Store Demo ---")
    db = BeaverDB("demo.db")

    # Set various data types
    db.set("app_config", {"theme": "dark", "retries": 3})
    db.set("user_ids", [101, 205, 301])
    db.set("session_active", True)
    db.set("welcome_message", "Hello, Beaver!")

    # Retrieve and print the data
    config = db.get("app_config")
    print(f"Retrieved config: {config}")
    print(f"Theme from config: {config.get('theme')}")

    ids = db.get("user_ids")
    print(f"Retrieved user IDs: {ids}")

    # Check for a non-existent key
    non_existent = db.get("non_existent_key")
    print(f"Result for non_existent_key: {non_existent}")

    db.close()
    print("-" * 35 + "\n")


if __name__ == "__main__":
    # To run this demo, save the file as beaver.py and run `python beaver.py`
    print("--- BeaverDB Pub/Sub Demo ---")
    kv_store_demo()
