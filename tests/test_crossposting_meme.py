from src.flows.crossposting.meme import _clean_caption


def test_strips_reddit_url():
    assert _clean_caption("https://redd.it/1rzi593") == ""


def test_strips_reddit_com_url():
    assert _clean_caption("https://www.reddit.com/r/me_irl/comments/abc") == ""


def test_strips_tg_handle():
    assert _clean_caption("@r_me_irl") == ""


def test_strips_subreddit_name():
    assert _clean_caption("me_irl") == ""


def test_strips_all_attribution_lines():
    caption = "me_irl\nhttps://redd.it/1rzi593\n@r_me_irl"
    assert _clean_caption(caption) == ""


def test_preserves_real_caption():
    caption = "When you finally fix the bug after 3 hours"
    assert _clean_caption(caption) == caption


def test_strips_attribution_preserves_real_content():
    caption = "me_irl\nhttps://redd.it/abc\n@r_me_irl\nThis is a real caption with multiple words"
    assert _clean_caption(caption) == "This is a real caption with multiple words"


def test_empty_string():
    assert _clean_caption("") == ""


def test_whitespace_only():
    assert _clean_caption("  \n  ") == ""
