import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from async_asgi_testclient import TestClient


@pytest.fixture(autouse=True, scope="session")
def run_migrations() -> None:
    import os

    print("running migrations..")
    os.system("alembic upgrade head")
    yield
    os.system("alembic downgrade base")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
