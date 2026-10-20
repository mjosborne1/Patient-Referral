FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first
COPY requirements.txt .

# Install pipenv and dependencies from requirements.txt
RUN pip install --no-cache-dir pipenv && \
    pipenv install -r requirements.txt && \
    pipenv requirements > requirements.frozen.txt && \
    pip install -r requirements.frozen.txt && \
    pip uninstall -y pipenv virtualenv-clone virtualenv

# Copy application code
COPY . .

# Version metadata from the build (see .github/workflows/docker-build.yml); GIT_SHA is
# reported by GET /version.
ARG APP_VERSION=unknown
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
LABEL org.opencontainers.image.version=${APP_VERSION} \
      org.opencontainers.image.revision=${GIT_SHA}

# Expose port for Flask application
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]