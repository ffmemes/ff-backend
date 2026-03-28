import pytest
import pytest_asyncio

from src.database import engine


@pytest.fixture(autouse=True, scope="session")
def run_migrations() -> None:
    import os

    print("running migrations..")
    os.system("alembic upgrade head")
    yield
    os.system("alembic downgrade base")


@pytest_asyncio.fixture(autouse=True, scope="session", loop_scope="session")
async def _dispose_engine():
    """Dispose stale pool connections so new ones bind to the session loop."""
    await engine.dispose()
    yield
    await engine.dispose()
