import datetime
import logging
import re
import urllib.parse
from typing import Optional

import bs4

from src.storage.parsers.base import Scraper, ScraperException
from src.storage.parsers.constants import USER_AGENT
from src.storage.parsers.schemas import TgChannelPostParsingResult

logger = logging.getLogger(__name__)
_SINGLE_MEDIA_LINK_PATTERN = re.compile(r"^https://t\.me/[^/]+/\d+\?single$")
_STYLE_MEDIA_URL_PATTERN = re.compile(r"url\(\'(.*?)\'\)")


class TelegramChannelScraper(Scraper):
    """
    Parses source for memes
    :param tg_username: Telegram channel username
    :return: List with posts
    """

    name = "telegram-channel"

    def __init__(self, tg_username: str, **kwargs):
        super().__init__(**kwargs)
        self._name = tg_username
        self._headers = {"User-Agent": USER_AGENT}
        self.base_url = "https://t.me"

    async def _initial_page(self):
        req = await self._request(
            f"{self.base_url}/s/{self._name}", headers=self._headers
        )
        if req.status_code != 200:
            raise ScraperException(f"Got status code {req.status_code}")
        r = await req.aread()
        return req, bs4.BeautifulSoup(r.decode("utf-8"), "lxml")

    async def get_items(
        self, num_of_posts: Optional[int] = None
    ) -> list[TgChannelPostParsingResult]:
        r, soup = await self._initial_page()
        if "/s/" not in str(r.url):
            logger.warning("No public post list for this user")
            return []
        next_page_url = ""
        raw_posts, posts = [], []
        if num_of_posts:
            total_posts = num_of_posts  # get only needed posts, not all
        else:
            total_posts = int(
                soup.find("a", attrs={"class": "tgme_widget_message_date"}, href=True)[
                    "href"
                ].split("/")[-1]
            )
        for _ in range(total_posts // 10):
            raw_posts.extend(
                soup.find_all(
                    "div", attrs={"class": "tgme_widget_message", "data-post": True}
                )
            )
            page_link = soup.find(
                "a", attrs={"class": "tme_messages_more", "data-before": True}
            )
            if not page_link:
                if "=" not in next_page_url:
                    next_page_url = soup.find(
                        "link", attrs={"rel": "canonical"}, href=True
                    )["href"]
                next_post_index = int(next_page_url.split("=")[-1]) - 20
                if next_post_index > 20:
                    page_link = {
                        "href": next_page_url.split("=")[0] + f"={next_post_index}"
                    }
                else:
                    break
            next_page_url = urllib.parse.urljoin(self.base_url, page_link["href"])
            req = await self._request(next_page_url, headers=self._headers)
            r = await req.aread()
            if req.status_code != 200:
                logger.fatal(
                    f"Status: {req.status_code}. Got {len(raw_posts)} / {total_posts}."
                )
                break
            soup = bs4.BeautifulSoup(r.decode("utf-8"), "lxml")
        raw_posts = reversed(raw_posts)
        if num_of_posts:
            counter = 0
            for post in raw_posts:
                posts.append(await self.get_post_details(post))
                counter += 1
                if counter == num_of_posts:
                    break
        else:
            for post in raw_posts:
                posts.append(await self.get_post_details(post))
        return posts

    async def get_post_details(self, post) -> TgChannelPostParsingResult:
        post_date_obj = post.find("div", class_="tgme_widget_message_footer").find(
            "a", class_="tgme_widget_message_date"
        )

        raw_url = post_date_obj["href"]
        if (
            not raw_url.startswith(self.base_url)
            or sum(x == "/" for x in raw_url) != 4
            or raw_url.rsplit("/", 1)[1].strip("0123456789") != ""
        ):
            logger.warning(f"Possibly incorrect URL: {raw_url!r}")

        post_date = datetime.datetime.strptime(
            post_date_obj.find("time", datetime=True)["datetime"]
            .replace("-", "", 2)
            .replace(":", ""),
            "%Y%m%dT%H%M%S%z",
        ).replace(tzinfo=None)

        url = raw_url.replace("//t.me/", "//t.me/s/")

        media = []
        outlinks = []
        mentions = []
        hashtags = []
        forwarded = None
        forwarded_url = None

        if forward_tag := post.find(
            "a", class_="tgme_widget_message_forwarded_from_name"
        ):
            forwarded_url = forward_tag["href"]
            forwarded_name = forwarded_url.split("t.me/")[1].split("/")[0]
            forwarded = {"username": forwarded_name}

        if message := post.find("div", class_="tgme_widget_message_text"):
            content = message.get_text(separator="\n")
        else:
            content = None

        for link in post.find_all("a"):
            if any(
                x in link.parent.attrs.get("class", [])
                for x in ("tgme_widget_message_user", "tgme_widget_message_author")
            ):
                continue

            if link["href"] == raw_url or link["href"] == url:
                style = link.attrs.get("style", "")
                if style != "":
                    imge_urls = _STYLE_MEDIA_URL_PATTERN.findall(style)
                    imge_urls = [{"url": i} for i in imge_urls]
                    media.extend(imge_urls)
                    continue

            if _SINGLE_MEDIA_LINK_PATTERN.match(link["href"]):
                style = link.attrs.get("style", "")
                imge_urls = _STYLE_MEDIA_URL_PATTERN.findall(style)
                imge_urls = [{"url": i} for i in imge_urls]
                media.extend(imge_urls)
                continue

            if link.text.startswith("@"):
                mentions.append(link.text.strip("@"))
                continue

            if link.text.startswith("#"):
                hashtags.append(link.text.strip("#"))
                continue

            href = urllib.parse.urljoin(self.base_url, link["href"])

            if (href not in outlinks) and (href != raw_url) and (href != forwarded_url):
                outlinks.append(href)

        for videoplayer in post.find_all(
            "a", {"class": "tgme_widget_message_video_player"}
        ):
            itag = videoplayer.find("i")
            if itag is None:
                video_url = None
                video_thumbnail_url = None
            else:
                style = itag["style"]
                video_thumbnail_url = _STYLE_MEDIA_URL_PATTERN.findall(style)[0]
                video_tag = videoplayer.find("video")
                video_url = None if video_tag is None else video_tag["src"]

            video_data = {
                "thumbnailUrl": video_thumbnail_url,
                "url": video_url,
            }
            time_tag = videoplayer.find("time")
            if time_tag is not None:
                video_data["duration"] = _duration_str_to_seconds(
                    videoplayer.find("time").text
                )

            media.append(video_data)

        link_preview = {}
        if link_preview_a := post.find("a", class_="tgme_widget_message_link_preview"):
            link_preview = {}
            link_preview["href"] = urllib.parse.urljoin(
                self.base_url, link_preview_a["href"]
            )
            if site_name_div := link_preview_a.find(
                "div", class_="link_preview_site_name"
            ):
                link_preview["siteName"] = site_name_div.text
            if title_div := link_preview_a.find("div", class_="link_preview_title"):
                link_preview["title"] = title_div.text
            if description_div := link_preview_a.find(
                "div", class_="link_preview_description"
            ):
                link_preview["description"] = description_div.text
            if image_i := link_preview_a.find("i", class_="link_preview_image"):
                if image_i["style"].startswith("background-image:url('"):
                    link_preview["image"] = image_i["style"][
                        22 : image_i["style"].index("'", 22)
                    ]
                else:
                    logger.warning(f"Could not process link preview image on {url}")
            if link_preview["href"] in outlinks:
                outlinks.remove(link_preview["href"])

        views_span = post.find("span", class_="tgme_widget_message_views")
        views = 0 if views_span is None else _parse_num(views_span.text)

        return TgChannelPostParsingResult(
            post_id=int(url.split("/")[-1]),
            url=url,
            date=post_date,
            content=content,
            media=media,
            mentions=mentions,
            hashtags=hashtags,
            forwarded=forwarded,
            forwarded_url=forwarded_url,
            link_preview=link_preview,
            out_links=outlinks,
            views=views,
        )


def _duration_str_to_seconds(duration_str: str):
    duration_list = duration_str.split(":")
    return sum(
        [int(s) * int(g) for s, g in zip([1, 60, 3600], reversed(duration_list))]
    )


def _parse_num(s: str):
    s = s.replace(" ", "")
    if s.endswith("M"):
        return int(float(s[:-1]) * 1e6)
    elif s.endswith("K"):
        return int(float(s[:-1]) * 1000)
    return int(s)
