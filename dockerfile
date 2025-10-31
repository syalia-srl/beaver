# Use a lightweight Python base image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Add a build argument for the version, defaulting to the latest
ARG VERSION=latest

# Install the specified version of beaver-db from PyPI
# If VERSION is "latest", it installs the most recent version.
# Otherwise, it installs the specified version (e.g., beaver-db==0.17.6)
RUN if [ "${VERSION}" = "latest" ]; then \
        pip install --no-cache-dir "beaver-db[full]"; \
    else \
        pip install --no-cache-dir "beaver-db[full]==${VERSION}"; \
    fi

# Set default environment variables for configuration
ENV DATABASE=beaver.db
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose the port the server will run on
EXPOSE 8000

# The command to run when the container starts
CMD ["beaver", "serve", "--database", "${DATABASE}", "--host", "${HOST}", "--port", "${PORT}"]