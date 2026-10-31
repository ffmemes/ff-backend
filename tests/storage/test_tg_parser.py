import bs4
import pytest

from src.storage.parsers.tg import TelegramChannelScraper

# Markup trimmed from a real t.me/s/<channel> page (2026-10-31).
POST_HTML = """
<div class="tgme_widget_message" data-post="chan/{post_id}">
  {reactions}
  <div class="tgme_widget_message_footer compact js-message_footer">
    <span class="tgme_widget_message_views">12.3K</span>
    <a class="tgme_widget_message_date" href="https://t.me/chan/{post_id}">
      <time datetime="2026-10-31T10:00:00+00:00" class="time">10:00</time>
    </a>
  </div>
</div>
"""

REACTIONS_HTML = (
    '<div class="tgme_widget_message_reactions js-message_reactions">'
    '<span class="tgme_reaction tgme_reaction_paid">'
    '<i class="icon icon-telegram-stars"></i>12</span>'
    '<span class="tgme_reaction"><i class="emoji"><b>👍</b></i>1.2K</span>'
    '<span class="tgme_reaction"><tg-emoji emoji-id="5373223594484587136"></tg-emoji>9.57K</span>'
    '<span class="tgme_reaction"><i class="emoji"><b>😁</b></i>7</span>'
    "</div>"
)


async def _parse(reactions_html: str):
    html = POST_HTML.format(post_id=42, reactions=reactions_html)
    post = bs4.BeautifulSoup(html, "lxml").find("div", class_="tgme_widget_message")
    return await TelegramChannelScraper("chan").get_post_details(post)


@pytest.mark.asyncio
async def test_reactions_summed_with_abbreviations():
    result = await _parse(REACTIONS_HTML)
    assert result.views == 12_300
    assert result.reactions == 12 + 1200 + 9570 + 7


@pytest.mark.asyncio
async def test_no_reactions_block_is_none():
    result = await _parse("")
    assert result.reactions is None
