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
    min_dislike_to_like_ratio: float | None = None,
    meme_source_column: str = "M.meme_source_id",
) -> str:
    """Hard-exclude sources the user clearly hates (optional, off by default).

    Skip/dislike in the feed UI is closer to TikTok "next" than "not interested".
    Hard exclusion of every majority-dislike source empties pools and treats skips
    as bans. Prefer :func:`disliked_source_demote_sql` for ranking demotion.

    Hard block only when ``ndislikes >= ratio * nlikes`` with enough reactions.
    """
    if enabled is None:
        from src.config import settings

        enabled = settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES
    if not enabled:
        return ""

    if min_reactions is None:
        from src.config import settings

        min_reactions = settings.RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS
    if min_dislike_to_like_ratio is None:
        from src.config import settings

        min_dislike_to_like_ratio = settings.RECOMMENDATION_BLOCK_DISLIKED_RATIO

    min_reactions = max(1, int(min_reactions))
    ratio = float(min_dislike_to_like_ratio)
    # ratio is config float, not user input
    return f"""
            AND NOT EXISTS (
                SELECT 1
                FROM user_meme_source_stats umss_block
                WHERE umss_block.user_id = :user_id
                  AND umss_block.meme_source_id = {meme_source_column}
                  AND (umss_block.nlikes + umss_block.ndislikes) >= {min_reactions}
                  AND umss_block.ndislikes >= {ratio} * GREATEST(umss_block.nlikes, 1)
            )
    """


def disliked_source_demote_sql(
    umss_alias: str = "UMSS",
    *,
    enabled: bool | None = None,
    min_reactions: int | None = None,
    multiplier: float | None = None,
) -> str:
    """SQL expression (not AND-clause): score multiplier for soft-disliked sources.

    Multiply into ORDER BY so majority-dislike sources are deprioritized but not
    removed — keeps the feed full for heavy skippers.
    """
    if enabled is None:
        from src.config import settings

        enabled = settings.RECOMMENDATION_DEMOTE_DISLIKED_SOURCES
    if not enabled:
        return "1.0"

    if min_reactions is None:
        from src.config import settings

        min_reactions = settings.RECOMMENDATION_DEMOTE_DISLIKED_MIN_REACTIONS
    if multiplier is None:
        from src.config import settings

        multiplier = settings.RECOMMENDATION_DEMOTE_DISLIKED_MULTIPLIER

    min_reactions = max(1, int(min_reactions))
    multiplier = float(multiplier)
    return f"""
            CASE
                WHEN {umss_alias}.ndislikes IS NOT NULL
                    AND {umss_alias}.ndislikes > {umss_alias}.nlikes
                    AND ({umss_alias}.nlikes + {umss_alias}.ndislikes) >= {min_reactions}
                THEN {multiplier}
                ELSE 1.0
            END
    """
