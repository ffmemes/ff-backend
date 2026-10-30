from urllib.parse import parse_qs, urlparse

from src.tgbot.sharing import (
    build_meme_share_button,
    get_meme_share_link,
    get_meme_share_url,
    parse_meme_share_deep_link,
)


def test_parse_meme_share_deep_link():
    parsed = parse_meme_share_deep_link("m_10001_20002")

    assert parsed is not None
    assert parsed.sharer_user_id == 10001
    assert parsed.meme_id == 20002

    legacy_parsed = parse_meme_share_deep_link("s_10001_20002")
    assert legacy_parsed is not None
    assert legacy_parsed.sharer_user_id == 10001
    assert legacy_parsed.meme_id == 20002

    assert parse_meme_share_deep_link("m_10001_20002_extra") is None
    assert parse_meme_share_deep_link("ir_10001_20002") is None


def test_get_meme_share_url_wraps_start_deep_link():
    share_url = get_meme_share_url(10001, 20002, "en")
    parsed = urlparse(share_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "t.me"
    assert parsed.path == "/share/url"
    assert query["url"] == [get_meme_share_link(10001, 20002)]
    assert query["text"] == ["Check out this meme"]
    assert "start=m_10001_20002" in query["url"][0]


def test_build_url_share_button():
    button = build_meme_share_button(
        meme_id=20002,
        user_id=10001,
        text="Send to a friend",
        interface_lang="en",
    )

    assert button.text == "Send to a friend"
    assert button.url.startswith("https://t.me/share/url?")
    assert button.switch_inline_query_chosen_chat is None
