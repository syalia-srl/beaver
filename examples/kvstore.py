from beaver import BeaverDB


def dict_store_demo():
    """Demonstrates the namespaced dictionary functionality."""
    print("--- Running Namespaced Dictionary Store Demo ---")
    db = BeaverDB("demo.db")

    # Get a handle to a namespaced dictionary called 'app_config'
    config = db.dict("app_config")

    # --- 1. Setting Values ---
    # Use the dictionary-style assignment
    config["theme"] = "dark"
    config["retries"] = 3

    # Or use the explicit .set() method
    config.set("user_ids", [101, 205, 301])
    config.set("session_active", True)

    print(f"Configuration dictionary has {len(config)} items.")

    # --- 2. Retrieving Values ---
    # Use dictionary-style access
    theme = config["theme"]
    print(f"Retrieved theme: {theme}")

    # Use the .get() method with a default value
    retries = config.get("retries")
    print(f"Retrieved retries: {retries}")

    non_existent = config.get("non_existent_key", "default_value")
    print(f"Result for non_existent_key: {non_existent}")

    # --- 3. Iterating Over the Dictionary ---
    print("\nIterating over config items:")
    for key, value in config.items():
        print(f"  - {key}: {value}")

    # --- 4. Deleting an Item ---
    del config["session_active"]
    print(f"\nAfter deleting 'session_active', config has {len(config)} items.")
    print(f"Is 'session_active' still in config? {'session_active' in config}")

    db.close()
    print("-" * 35 + "\n")


if __name__ == "__main__":
    print("--- BeaverDB Dictionary Store Demo ---")
    dict_store_demo()
