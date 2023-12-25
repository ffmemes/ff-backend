import itertools
from typing import List, Optional

import pandas as pd
from sqlalchemy import text

from src.storage.parsers.snscrape.modules.telegram import TelegramChannelScraper
from src.database import simple_engine, fetch_raw_sql, parsed_memes_telegram


def _get_channel_list() -> List[dict]:
    """
    Returns a list of channels to parse
    To start getting posts from a channel, insert row with channel_id to table
    channel_id can be found here https://t.me/s/{channel_id}/
    If you want to start getting posts from the beginning, set created_at to None
    Otherwise, set created_at to the date from which you want to collect
    :return: List of channels
    """
    sql_query = text(f'SELECT channel_id, MAX(created_at)::timestamptz created_at FROM {parsed_memes_telegram.name} '
                     f'GROUP BY channel_id')
    results = fetch_raw_sql(sql_query)
    return results


def parse_channels(channels: List[dict], num_of_posts: Optional[int] = None) -> pd.DataFrame:
    """
    Parses a list of channels
    :param channels: List of channels
    :param num_of_posts: Number of posts to scrape
    :return: DataFrame with posts
    """
    df_all_posts = pd.DataFrame()
    for channel in channels:
        data = []
        tg = TelegramChannelScraper(channel["channel_id"])
        post_list = tg.get_items()
        if num_of_posts is None:
            if channel["created_at"] is None:
                data.extend(post_list)
            else:
                batch_size = 10
                while True:
                    data.extend([next(itertools.islice(post_list, None, None)) for _ in range(batch_size)])
                    if data[-1].date < channel["created_at"]:
                        break
        else:
            data.extend([next(itertools.islice(post_list, None, None)) for _ in range(num_of_posts)])
        df = pd.DataFrame(data)
        df.rename(columns={'date': 'created_at'}, inplace=True)
        if channel["created_at"]:
            df = df.loc[df["created_at"] > channel["created_at"]]
        df["channel_id"] = channel["channel_id"]
        df["post_id"] = df["url"].apply(lambda x: x.split("/")[-1])
        df["views"] = df["views"].apply(lambda x: x[0] if x else 0)
        df["media"] = df["media"].apply(lambda x: [i["url"] for i in x] if x else x)
        df = df[['channel_id', 'post_id', 'created_at', 'views', 'content', 'media']]
        df_all_posts = pd.concat([df_all_posts, df], ignore_index=True)
    return df_all_posts


def insert_data(df: pd.DataFrame()) -> None:
    """
    Inserts data into the database
    :param df: DataFrame with posts
    :return: None
    """
    df["insert_type"] = 1
    df.to_sql(parsed_memes_telegram.name, simple_engine, if_exists='append', index=False,  chunksize=1000)


def parse_source(num_of_posts: Optional[int] = None) -> None:
    """
    Processes telegram channels
    :param num_of_posts: Number of posts to scrape
    :return: None
    """
    channels = _get_channel_list()
    df = parse_channels(channels, num_of_posts)
    if df.shape[0] > 0:
        insert_data(df)


if __name__ == '__main__':
    parse_source()
