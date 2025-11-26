# Deployment

Deploying BeaverDB is fundamentally different from deploying client-server databases like Postgres or Redis. Because BeaverDB is **embedded**, there is no separate "Database Server" to install, configure, or maintain.

Your database is just a file (`app.db`) that lives alongside your code.

## 1. The Single-File Philosophy

In a traditional stack, you have:
* **App Server:** Python code (Stateless)
* **DB Server:** Postgres/MySQL (Stateful)
* **Cache:** Redis (Stateful)

In a **BeaverDB** stack, you have:
* **App Server:** Python code + `app.db` (Stateful)

### Advantages
* **Zero Latency:** No network round-trips. Data access is instant.
* **Atomic Backups:** Backing up your entire state (Users + Search Index + Logs) is just copying one file.
* **Simplified CI/CD:** You don't need to spin up DB containers in your GitHub Actions. Just run your tests.

## 2. Deployment Strategies

### Scenario A: Embedded (Recommended)

The database runs inside your application process.

* **Use Case:** CLI tools, Desktop apps, Single-instance web apps (e.g., a VPS running one FastAPI service).
* **Setup:** Just ensure the process has **Write Permissions** to the directory containing the `.db` file.

### Scenario B: Multi-Process Workers

You run multiple instances of your app (e.g., `gunicorn -w 4` or multiple background workers).

* **Setup:** All processes must share access to the **same filesystem volume**.
* **Concurrency:** BeaverDB handles the locking. You don't need to do anything special.
* **Limitation:** This works on a single machine (VPS/Dedicated Server). It does *not* work across different servers (e.g., AWS Lambda or Heroku Dynos) unless you mount a shared network file system like EFS (which effectively works but adds latency).

### Scenario C: Client-Server Mode

If you need to access the database from multiple distinct machines, or from a browser/mobile app, run BeaverDB as a standalone server.

```bash
# Start the server
beaver serve ./my_app.db --host 0.0.0.0 --port 8080
```

Then connect using the HTTP Client:

```python
from beaver import BeaverClient

# Works exactly like BeaverDB locally
db = BeaverClient("http://localhost:8080")
```

## 3. Dockerizing BeaverDB

Since the database is a file, you must ensure it persists when the container restarts. Use a **Docker Volume**.

### `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install "beaver-db[all]"

# Copy app code
COPY . .

# Create a directory for the database
RUN mkdir /data

# Run the app (pointing DB to the volume)
CMD ["python", "main.py", "--db-path", "/data/app.db"]
```

### `docker-compose.yml`

```yaml
services:
  app:
    build: .
    volumes:
      - beaver_data:/data
    ports:
      - "8000:8000"

volumes:
  beaver_data:
```

## 4. Backups & Restore

### Hot Backup (Recommended)

You cannot just copy the `.db` file while the app is writing to it (you might get a corrupted "torn page").
Use the `beaver dump` command or the SQLite Online Backup API.

**Using CLI:**

```bash
# Safely backup the database while it is running
beaver dump my_app.db > backup_$(date +%F).json
```

**Using Python:**

```python
import sqlite3

def backup(source_db_path, backup_path):
    src = sqlite3.connect(source_db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
```

### Restore

To restore, simply stop your application and replace the `.db` file with your backup copy.

## 5. Performance Tuning

For high-throughput production environments, consider these settings:

### WAL Mode (Write-Ahead Logging)

BeaverDB enables `WAL` mode by default. This allows concurrent readers and writers. **Do not disable this.**

### Memory Mapping (`mmap`)

If your database fits within your server's RAM, enabling memory mapping can significantly boost read performance. BeaverDB enables this by default with a 256MB limit.

You can adjust this limit during initialization:

```python
# Enable mmap for a 2GB database
db = BeaverDB(
    "app.db",
    pragma_mmap_size=2 * 1024 * 1024 * 1024  # 2GB
)
```

### Batching

For bulk ingestion (ETL jobs), always use `.batched()`.

  * **Bad:** 10,000 `db.dict["key"] = val` calls = 10,000 transactions (\~20s).
  * **Good:** `with db.dict.batched()...` = 1 transaction (\~0.1s).
