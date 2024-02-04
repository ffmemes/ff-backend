import datetime
import logging
import random
import time

import httpx

logger = logging.getLogger(__name__)


def lerp(
    a1: int = datetime.date(2023, 1, 1).toordinal(),
    b1: int = datetime.date(2030, 12, 31).toordinal(),
    a2: int = 111,
    b2: int = 200,
    n: int = datetime.date.today().toordinal(),
) -> int:
    return int((n - a1) / (b1 - a1) * (b2 - a2) + a2)


def _random_user_agent():
    """Adopt Chrome's UA reduction scheme and choose a random reasonable UA"""
    version = lerp()
    version += random.randint(-5, 1)
    version = max(version, 101)
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"  # noqa: E501


class ScraperException(Exception):
    pass


class Scraper:
    """Base class for Scraper"""

    def __init__(self, *, retries=3):
        self._retries = retries
        self._client = httpx.AsyncClient(follow_redirects=True)

    def get_items(self):
        """Base method for getting items from source"""
        pass

    async def _request(self, url: str, headers: dict = None, method="GET"):
        errors = []
        if not headers:
            headers = {}
        if "User-Agent" not in headers:
            headers["User-Agent"] = _random_user_agent()
        for attempt in range(self._retries + 1):
            logger.info(f"Retrieving {url}")
            try:
                req = self._client.build_request(method, url, headers=headers)
                r = await self._client.send(req, stream=True)
                logger.debug(f"{url} retrieved successfully")
                return r
            except httpx.RequestError as exc:
                if attempt < self._retries:
                    retrying = ", retrying"
                    level = logging.INFO
                else:
                    retrying = ""
                    level = logging.ERROR
                logger.log(level, f"Error retrieving {url}: {exc!r}{retrying}")
                errors.append(repr(exc))
            except httpx.InvalidURL as exc:
                logger.error(exc)
            if attempt < self._retries:
                sleep_time = 1.0 * 2**attempt  # exponential backoff
                logger.info(f"Waiting {sleep_time:.0f} seconds")
                time.sleep(sleep_time)
        msg = f"{self._retries + 1} requests to {url} failed, giving up."
        logger.fatal(msg)
        logger.fatal(f'Errors: {", ".join(errors)}')
