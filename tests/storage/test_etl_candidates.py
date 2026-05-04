import pytest

from src.storage.etl import normalize_telegram_channel_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://t.me/somechannel", "https://t.me/somechannel"),
        ("https://t.me/SomeChannel", "https://t.me/somechannel"),
        ("https://t.me/somechannel/", "https://t.me/somechannel"),
        ("https://t.me/somechannel/12345", "https://t.me/somechannel"),
        ("https://t.me/s/somechannel/12345", "https://t.me/somechannel"),
        ("http://t.me/somechannel/12345", "https://t.me/somechannel"),
        # Query strings and fragments must collapse onto the canonical form so
        # manual moderator entries dedupe against discovery-pipeline candidates.
        ("https://t.me/somechannel?utm_source=share", "https://t.me/somechannel"),
        ("https://t.me/somechannel/?utm_source=share", "https://t.me/somechannel"),
        ("https://t.me/somechannel/12345?single", "https://t.me/somechannel"),
        ("https://t.me/somechannel#anchor", "https://t.me/somechannel"),
        # Private/invite links and aliases must not become candidates.
        ("https://t.me/joinchat/abc123", None),
        ("https://t.me/+invite", None),
        ("https://example.com/", None),
        ("", None),
    ],
)
def test_normalize_telegram_channel_url(raw, expected):
    assert normalize_telegram_channel_url(raw) == expected
