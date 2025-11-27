# Stage 1: The "Builder" stage
# This stage installs all build tools, copies the source code,
# and builds the application with all its dependencies into a virtual environment.
FROM python:3.12-slim as builder

# Install curl first, as root, and clean up apt cache
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv, our package manager, as root using the official installer
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

# Change user to the non-root user
WORKDIR /app

# Copy only the files needed for dependency installation
COPY pyproject.toml uv.lock README.md ./

# Install all dependencies, including the 'full' extras
# The 'full' extra includes 'remote', which is needed for 'beaver serve'
RUN uv sync --all-extras --all-groups --no-editable

# Copy the rest of the source code
COPY . .

# Install the beaver-db package itself from the local source code
# This builds the package and installs it into the venv
RUN uv pip install .[full]

# ---

# Stage 2: The "Final" stage
# This is a clean Python image that will only contain the
# virtual environment with the installed application.
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy *only* the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

# Set default environment variables for configuration
ENV DATABASE=beaver.db
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose the port the server will run on
EXPOSE 8000

# The command to run when the container starts
# Use the "shell" form (a plain string) so that environment variables
# like ${PORT} are correctly interpolated by the shell.
CMD beaver serve --database "${DATABASE}" --host "${HOST}" --port "${PORT}"
