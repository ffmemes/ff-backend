import dataclasses

from src.storage.parsers.snscrape.modules.telegram import TelegramChannelScraper
from src.storage.parsers.schemas import TgChannelPostParsingResult

# TODO: async + requests -> httpx
def parse_tg_channel(
    tg_username: str, 
    num_of_posts: int | None = None,
) -> list[TgChannelPostParsingResult]:
    """
    Parses source for memes
    :param source: Telegram channel
    :param num_of_posts: Number of posts to scrape
    :return: List with posts
    """
    posts = []
    tg = TelegramChannelScraper(tg_username)
    post_list = tg.get_items()
    try:
        if num_of_posts is None:
            while True:
                posts.append(dataclasses.asdict(next(post_list)))
        else:
            posts.extend([dataclasses.asdict(next(post_list)) for _ in range(num_of_posts)])
    except StopIteration:
        pass

    return [
        TgChannelPostParsingResult(
            post_id=int(post["url"].split("/")[-1]),
            url=post["url"],
            date=post["date"].replace(tzinfo=None),
            content=post["content"],
            media=post["media"],
            mentions=post["mentions"],
            hashtags=post["hashtags"],
            forwarded_from=post["forwarded"],
            forwarded_url=post["forwardedUrl"],
            link_preview=post["linkPreview"],
            out_links=post["outlinks"],
            views=post["views"][0] if post["views"] else 0,
        )
        for post in posts
    ]
