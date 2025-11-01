# Deployment & Access

**Chapter Outline:**

* **8.1. The REST API Server (`beaver serve`)**
    * Exposing your database as a FastAPI application.
    * Command: `beaver serve --database my.db --port 8000`
    * Accessing the interactive OpenAPI docs at `/docs`.
* **8.2. The Command-Line Client (`beaver client`)**
    * Interacting with your database from the terminal for admin and debugging.
    * Example: `beaver client --database my.db dict config get theme`
* **8.3. Docker Deployment**
    * Running the server in a container for stable deployment.
    * `docker run -p 8000:8000 -v $(pwd)/data:/app apiad/beaverdb`
