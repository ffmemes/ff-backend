def exclude_meme_ids_sql_filter(exclude_meme_ids: list[int], meme_id_column: str = "M.id") -> str:
    """Return a SQL fragment to exclude meme IDs using parameterized array.

    Uses ANY(:exclude_meme_ids) with a bound parameter instead of
    string interpolation to prevent SQL injection.
    """
    if exclude_meme_ids:
        return f"AND {meme_id_column} != ALL(:exclude_meme_ids)"
    return ""


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
