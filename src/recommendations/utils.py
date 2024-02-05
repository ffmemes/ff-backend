def exclude_meme_ids_sql_filter(
    exclude_meme_ids: list[int], meme_id_column: str = "M.id"
) -> str:
    if len(exclude_meme_ids) > 1:
        exclude = f"AND {meme_id_column} NOT IN {tuple(exclude_meme_ids)}"
    elif len(exclude_meme_ids) == 1:
        exclude = f"AND {meme_id_column} != {exclude_meme_ids[0]}"
    else:
        exclude = ""
    return exclude
