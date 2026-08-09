def exclude_meme_ids_sql_filter(exclude_meme_ids: list[int], meme_id_column: str = "M.id") -> str:
    """Return a SQL fragment to exclude meme IDs using parameterized array.

    Uses ANY(:exclude_meme_ids) with a bound parameter instead of
    string interpolation to prevent SQL injection.
    """
    if exclude_meme_ids:
        return f"AND {meme_id_column} != ALL(:exclude_meme_ids)"
    return ""


def block_disliked_sources_sql_filter(
    *,
    enabled: bool | None = None,
    min_reactions: int | None = None,
    meme_source_column: str = "M.meme_source_id",
) -> str:
    """Exclude memes from sources the user already dislikes more than likes.

    Uses user_meme_source_stats (updated with reaction stats). Requires at least
    ``min_reactions`` prior reactions on that source so cold-start noise does
    not ban a channel after one accidental dislike.

    ``min_reactions`` is validated as int before interpolation (not user input).
    """
    if enabled is None:
        from src.config import settings

        enabled = settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES
    if not enabled:
        return ""

    if min_reactions is None:
        from src.config import settings

        min_reactions = settings.RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS

    min_reactions = max(1, int(min_reactions))
    return f"""
            AND NOT EXISTS (
                SELECT 1
                FROM user_meme_source_stats umss_block
                WHERE umss_block.user_id = :user_id
                  AND umss_block.meme_source_id = {meme_source_column}
                  AND umss_block.ndislikes > umss_block.nlikes
                  AND (umss_block.nlikes + umss_block.ndislikes) >= {min_reactions}
            )
    """
