import pytest
import pytest_asyncio

from src.redis import pool as redis_pool


@pytest.fixture(autouse=True, scope="session")
def run_migrations() -> None:
    import os

    print("running migrations..")
    os.system("alembic upgrade head")
    yield
    os.system("alembic downgrade base")


@pytest_asyncio.fixture(autouse=True, scope="session", loop_scope="session")
async def _reset_redis_pool():
    """Ensure Redis pool starts fresh on the session event loop."""
    await redis_pool.disconnect()
    yield
    await redis_pool.disconnect()
