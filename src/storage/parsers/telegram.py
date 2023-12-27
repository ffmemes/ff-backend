import dataclasses

from src.storage.parsers.snscrape.modules.telegram import TelegramChannelScraper

# TODO: async + requests -> httpx
# TODO: -> List[TgChannelPostParsingResult]
def parse_tg_channel(tg_username: str, num_of_posts: int | None = None) -> list[dict]:
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

    for post in posts:
        post["forwarded_url"] = post.pop("forwardedUrl")
        post["link_preview"] = post.pop("linkPreview")
        post["out_links"] = post.pop("outlinks")
        post["post_id"] = int(post["url"].split("/")[-1])
        post["views"] = post["views"][0] if post["views"] else 0

    return posts
