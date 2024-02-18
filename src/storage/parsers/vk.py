import asyncio
import datetime
import json
import logging
from typing import Optional

from src.config import settings
from src.storage.parsers.base import Scraper, ScraperException
from src.storage.parsers.schemas import VkGroupPostParsingResult

logger = logging.getLogger(__name__)


class VkGroupScraper(Scraper):
    """
    Parses source for memes
    :param source_link: Vk group link
    :return: List with posts
    """

    name = "vk-group"

    def __init__(self, source_link, **kwargs):
        super().__init__(**kwargs)
        self.source_link = source_link
        self.vk_source_link = None
        self.VK_TOKEN = settings.VK_TOKEN
        self.base_url = "https://api.vk.com/method/wall.get?access_token={vk_token}&v={v}&domain={domain}&count=100&offset={offset}"

    async def get_items(
        self, num_of_posts: Optional[int] = None
    ) -> list[VkGroupPostParsingResult]:
        logger.info(f"Going to parse VK: {self.source_link}")
        vk_source = _extract_username_from_url(self.source_link)
        self.vk_source_link = "https://vk.com/%s" % vk_source
        r = await self._get_vk_wall(vk_source)
        if r is None or "response" not in r:
            logger.error(f"Can't parse vk, got response: {r}")
            return []

        posts = r["response"]["items"]
        posts_count = r["response"]["count"]
        if num_of_posts:
            posts_count = num_of_posts

        offset = 100
        while posts_count > len(posts):
            r = await self._get_vk_wall(vk_source, offset)
            if r is None:
                break
            posts.extend(r["response"]["items"])
            offset += 100
            await asyncio.sleep(5)  # to not to DDOS VK

        results = []
        for post in posts:
            post_details = await self.get_post_details(post)
            if post_details:
                results.append(post_details)

        return results

    async def _get_vk_wall(self, vk_source: str, offset: int = 0) -> Optional[dict]:
        if self.VK_TOKEN is None:
            logger.error("Can't parse vk without VK_TOKEN")
            return None
        req = await self._request(
            self.base_url.format(
                vk_token=self.VK_TOKEN, v="5.92", domain=vk_source, offset=offset
            )
        )
        if req.status_code != 200:
            raise ScraperException(f"Got status code {req.status_code}")
        r = await req.aread()
        return json.loads(r.decode("utf-8"))

    async def get_post_details(self, post: dict) -> VkGroupPostParsingResult | None:
        if post["marked_as_ads"] or "attachments" not in post:
            # ignoring ads & text-only publications
            return
        if set(["photo"]) != set(
            post["attachments"][i]["type"] for i in range(len(post["attachments"]))
        ):
            # work only with photos for now
            return

        if post["text"] and len(post["text"]) >= 200:
            return

        images = get_best_img(post)
        return VkGroupPostParsingResult(
            post_id=f'{post["from_id"]}_{post["id"]}',
            content=post["text"],
            date=datetime.datetime.fromtimestamp(post["date"]),
            media=images,
            url=get_post_link(post, self.vk_source_link),
            comments=post["comments"]["count"],
            likes=post["likes"]["count"],
            views=post["views"]["count"],
            reposts=post["reposts"]["count"],
        )


def _extract_username_from_url(vk_source: str) -> str:
    return vk_source[vk_source.find("vk.com/") + 7 :].replace("/", "")


def get_best_img(post: dict) -> list[str]:
    return [
        sorted(i["photo"]["sizes"], key=lambda x: -x["width"])[0]["url"]
        for i in post["attachments"]
    ]


def get_post_link(post: dict, vk_source_link: str) -> str:
    return "{vk_source_link}?w=wall{source_id}_{id}".format(
        vk_source_link=vk_source_link, source_id=post["from_id"], id=post["id"]
    )
