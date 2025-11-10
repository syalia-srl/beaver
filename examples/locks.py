import os
import time
from datetime import datetime
from beaver import BeaverDB

DB_PATH = "lock_test.db"
LOCK_NAME = "critical_task_lock"
SHARED_LOG_NAME = "shared_work_log"


def run_lock_demo():
    """
    A test function that demonstrates the inter-process lock.
    """
    pid = os.getpid()
    db = BeaverDB(DB_PATH)

    while True:
        print(f"[PID {pid}] Trying to acquire lock '{LOCK_NAME}' (timeout=5s)...")

        try:
            # Try to acquire the lock with a 5-second timeout
            # We use a short poll_interval for a responsive test
            with db.lock(LOCK_NAME, timeout=5.0, poll_interval=0.2):
                # --- CRITICAL SECTION START ---
                # Only one process can be in this block at a time.
                print(f"--------------------------------------------------")
                print(f"[PID {pid}] ✅ Lock ACQUIRED.")
                log_time = datetime.now().isoformat()

                print(f"[PID {pid}] 👷 Starting work (simulating 3 seconds)...")
                time.sleep(3)
                print(f"[PID {pid}] 🏁 Work finished.")

                print(f"[PID {pid}] 🔑 Releasing lock.")
                # --- CRITICAL SECTION END ---
                # Lock is automatically released when the 'with' block exits
                print(f"--------------------------------------------------")

        except TimeoutError:
            # This happens if we couldn't get the lock within the 5-second timeout
            print(
                f"[PID {pid}] ❌ Lock acquisition TIMED OUT. Another process is busy."
            )
        except Exception as e:
            print(f"[PID {pid}] An error occurred: {e}")


if __name__ == "__main__":
    print("--- BeaverDB Lock Test ---")
    print(f"To test, run this script in 2 or more terminals at the same time.")
    print("Database file: " + DB_PATH)
    print("------------------------\n")
    run_lock_demo()
