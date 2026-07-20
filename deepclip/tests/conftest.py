"""Test-wide configuration.

Set before any application module is imported, because the API reads these at
import time. Without them the suite pays a real connect-timeout to Postgres and
Redis on every TestClient startup, and SSE tests hold the stream open for the
full production timeout.
"""

import os

os.environ.setdefault("STARTUP_TIMEOUT_S", "0.05")
os.environ.setdefault("SSE_KEEPALIVE_S", "0.05")
os.environ.setdefault("SSE_TIMEOUT_S", "0.3")
# Never let a test accidentally reach a real service.
os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1")
