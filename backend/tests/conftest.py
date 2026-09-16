import os

os.environ.setdefault("DATABASE_URL", "postgresql://resolve:resolve@localhost:5432/resolve")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
