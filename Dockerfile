# Playwright base image bundles Chromium + every shared lib it needs, pinned
# to a known-good Python 3.11 environment. Avoids the apt-get dance of installing
# ~15 X11/font/codec deps on python:3.11-slim every build.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium is preinstalled in the base image; just verify it's available.
RUN python -c "from playwright.sync_api import sync_playwright; \
    p = sync_playwright().start(); \
    print('Chromium executable:', p.chromium.executable_path); \
    p.stop()"

COPY . .

# Render assigns $PORT dynamically (typically 10000); server.py reads it.
EXPOSE 10000

CMD ["python", "server.py"]
