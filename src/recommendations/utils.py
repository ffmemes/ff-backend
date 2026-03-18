def exclude_meme_ids_sql_filter(exclude_meme_ids: list[int], meme_id_column: str = "M.id") -> str:
    """Return a SQL fragment to exclude meme IDs using parameterized array.

    Uses ANY(:exclude_meme_ids) with a bound parameter instead of
    string interpolation to prevent SQL injection.
    """
    if exclude_meme_ids:
        return f"AND {meme_id_column} != ALL(:exclude_meme_ids)"
    return ""
