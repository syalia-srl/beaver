import time
from beaver import BeaverDB


def expensive_api_call(prompt: str):
    """A mock function that simulates a slow API call."""
    print(f"--- Making expensive API call for: '{prompt}' ---")
    time.sleep(2)  # Simulate network latency
    if prompt == "capital of Ecuador":
        return "Quito"
    return "Data not found"


def cache_demo():
    """Demonstrates using a namespaced dictionary as a persistent cache with TTL."""
    print("--- Running Cache Demo ---")
    db = BeaverDB("demo.db")

    # Use a dictionary as a cache. Items will expire after 10 seconds.
    api_cache = db.dict("api_cache")

    prompt = "capital of Ecuador"

    # --- 1. First Call (Cache Miss) ---
    print("\nAttempt 1: Key is not in cache.")
    response = api_cache.get(prompt)
    if response is None:
        print("Cache miss.")
        response = expensive_api_call(prompt)
        # Set the value in the cache with a 10-second TTL
        api_cache.set(prompt, response, ttl_seconds=10)

    print(f"Response: {response}")

    # --- 2. Second Call (Cache Hit) ---
    print("\nAttempt 2: Making the same request within 5 seconds.")
    time.sleep(5)
    response = api_cache.get(prompt)
    if response is None:
        print("Cache miss.")
        response = expensive_api_call(prompt)
        api_cache.set(prompt, response, ttl_seconds=10)
    else:
        print("Cache hit!")

    print(f"Response: {response}")

    # --- 3. Third Call (Cache Expired) ---
    print("\nAttempt 3: Waiting for 12 seconds for the cache to expire.")
    time.sleep(12)
    response = api_cache.get(prompt)
    if response is None:
        print("Cache miss (key expired).")
        response = expensive_api_call(prompt)
        api_cache.set(prompt, response, ttl_seconds=10)
    else:
        print("Cache hit!")

    print(f"Response: {response}")

    db.close()
    print("\n--- Demo Finished ---")


if __name__ == "__main__":
    cache_demo()
