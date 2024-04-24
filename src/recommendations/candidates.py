from typing import Any

from sqlalchemy import text

from src.database import fetch_all
from src.recommendations.utils import exclude_meme_ids_sql_filter


# "lr" - like rate
# I'm not sure about the naming, will change later
async def sorted_by_user_source_lr_meme_lr_meme_age(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'sorted_by_user_source_lr_meme_lr_meme_age' as recommended_by
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.user_id = {user_id}
            AND R.meme_id = M.id
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

		LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1), 0.5)
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


# like rate: 24%
async def most_liked(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'most_liked' as recommended_by
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.user_id = {user_id}
            AND R.meme_id = M.id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def multiply_all_scores(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id, M.type, M.telegram_file_id, M.caption,
            'multiply_all_scores' as recommended_by
        --    M.id
        --    , (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1) user_source
        --    , (MSS.nlikes + 1.) / (MSS.nlikes + MSS.ndislikes + 1) meme_source
        --    , (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1) meme
        --    , raw_impr_rank
        --    , MS.age_days
        --    , (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent meme_click_rate
        FROM meme M
        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}
        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        LEFT JOIN meme_source_stats MSS
            ON MSS.meme_source_id = M.meme_source_id

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL -- not seen
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * COALESCE((UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1), 0.5)
            * COALESCE((MSS.nlikes + 1.) / (MSS.nlikes + MSS.ndislikes + 1) , 0.5)
            * COALESCE((MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1), 0.5)
            * CASE WHEN MS.raw_impr_rank < 1 THEN 1 ELSE 0.5 END
            * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
            * CASE WHEN M.caption IS NULL THEN 1 ELSE 0.8 END
            * CASE
                WHEN MS.nmemes_sent <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
            END

        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def less_seen_meme_and_source(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        WITH LESS_SEEN_MEME_FROM_EACH_SOURCE AS (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'less_seen_meme_and_source' as recommended_by

                , M.meme_source_id
                , COALESCE(MS.nmemes_sent, 0) meme_sent_times
                , COALESCE(UMSS.nlikes + UMSS.ndislikes, 0) source_seen_times
            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.user_id = {user_id}
                AND R.meme_id = M.id

            INNER JOIN user_language L
                ON L.language_code = M.language_code
                AND L.user_id = {user_id}

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            LEFT JOIN user_meme_source_stats UMSS
                ON UMSS.meme_source_id = M.meme_source_id
                AND UMSS.user_id = {user_id}

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}

            ORDER BY
                M.meme_source_id, -- one meme from each source
                meme_sent_times
        )

        SELECT
            id, type, telegram_file_id, caption, recommended_by
        FROM LESS_SEEN_MEME_FROM_EACH_SOURCE
        ORDER BY source_seen_times -- less seen sources
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


# like rate: 38%
async def top_memes_from_less_seen_sources(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        WITH LESS_SEEN_SOURCES AS (
            SELECT
                MS.id,
                COALESCE(UMSS.nlikes + UMSS.ndislikes, 0) / 10 seen_times
            FROM meme_source MS
            LEFT JOIN user_meme_source_stats UMSS
                ON MS.id = UMSS.meme_source_id
                AND UMSS.user_id = {user_id}
            ORDER BY seen_times
        )

        SELECT
            M.id
            , M.type, M.telegram_file_id
            , M.caption, M.recommended_by

        FROM (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'less_seen_sources' as recommended_by,

                1
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.5 END
                    * CASE WHEN MS.age_days < 5 THEN 1 ELSE 0.5 END
                    * COALESCE((MS.nlikes+1.) / (MS.nlikes+MS.ndislikes+1), 0.5)
                    * COALESCE((MSS.nlikes+1.) / (MSS.nlikes+MSS.ndislikes+1), 0.5)
                AS score,
                M.meme_source_id

            FROM meme M

            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

            INNER JOIN user_language L
                ON L.user_id = {user_id}
                AND L.language_code = M.language_code

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            LEFT JOIN meme_source_stats MSS
                ON MSS.meme_source_id = M.meme_source_id

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}

            ORDER BY M.meme_source_id, score
        ) M
        INNER JOIN LESS_SEEN_SOURCES
            ON LESS_SEEN_SOURCES.id = M.meme_source_id
        ORDER BY seen_times, score DESC
        LIMIT {limit}

    """
    res = await fetch_all(text(query))
    return res


async def classic(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'classic' AS recommended_by

        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.language_code = M.language_code
            AND L.user_id = {user_id}

        LEFT JOIN user_meme_reaction R
            ON R.meme_id = M.id
            AND R.user_id = {user_id}

        LEFT JOIN user_meme_source_stats UMSS
            ON UMSS.meme_source_id = M.meme_source_id
            AND UMSS.user_id = {user_id}

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL
            AND MS.nlikes > 1
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}

        ORDER BY -1
            * (UMSS.nlikes + 1.) / (UMSS.nlikes + UMSS.ndislikes + 1.)
            * (MS.nlikes + 1.) / (MS.nlikes + MS.ndislikes + 1.)
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def like_spread_and_recent_memes(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption
            , 'like_spread_and_recent' AS recommended_by

            -- , MS.nlikes, MS.ndislikes
        FROM meme M
        INNER JOIN meme_stats MS
            ON MS.meme_id = M.id

        INNER JOIN user_language L
            ON L.user_id = {user_id}
            AND L.language_code = M.language_code

        LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

        WHERE 1=1
            AND M.status = 'ok'
            AND R.meme_id IS NULL

            AND MS.nlikes > MS.ndislikes
            AND MS.raw_impr_rank = 0
            AND age_days < 30
            {exclude_meme_ids_sql_filter(exclude_meme_ids)}
        ORDER BY -1
            * (MS.nlikes - MS.ndislikes) / (MS.nmemes_sent + 1.)
            * CASE WHEN MS.age_days < 30 THEN 1 ELSE 0.5 END
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def get_best_memes_from_each_source(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> list[dict[str, Any]]:
    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption, M.recommended_by
        FROM (
            SELECT DISTINCT ON (M.meme_source_id)
                M.id, M.type, M.telegram_file_id, M.caption,
                'best_meme_from_each_source' as recommended_by,

                1
                    * CASE WHEN MS.raw_impr_rank <= 1 THEN 1 ELSE 0.8 END
                    * CASE WHEN MS.age_days < 14 THEN 1 ELSE 0.8 END
                    * COALESCE((MS.nlikes+1.) / (MS.nlikes+MS.ndislikes+1), 0.5)
                    * CASE
                        WHEN MS.nmemes_sent <= 1 THEN 1
                        ELSE (MS.nlikes + MS.ndislikes) * 1. / MS.nmemes_sent
                    END
                AS score

            FROM meme M
            LEFT JOIN user_meme_reaction R
                ON R.meme_id = M.id
                AND R.user_id = {user_id}

            INNER JOIN user_language L
                ON L.user_id = {user_id}
                AND L.language_code = M.language_code

            LEFT JOIN meme_stats MS
                ON MS.meme_id = M.id

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY M.meme_source_id, score DESC
        ) M
        ORDER BY score DESC
        LIMIT {limit}
    """
    res = await fetch_all(text(query))
    return res


async def get_random_best(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    """Selects 'limit' best memes from the top 100 memes obtained using the cleared meme statistics
    The cleared statistics aggregates reactions from users with less than 200 previous reactions 
    It's aim is to remove the bias from old users
    """

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption, M.recommended_by
        FROM (
            SELECT
                M.id
                , M.type, M.telegram_file_id, M.caption
                , 'random_best_ab_240422' AS recommended_by
                , random() rand
            FROM meme M
            INNER JOIN meme_stats MS
                ON MS.meme_id = M.id

            INNER JOIN user_language L
                ON L.user_id = {user_id}
                AND L.language_code = M.language_code

            LEFT JOIN user_meme_reaction R
                    ON R.meme_id = M.id
                    AND R.user_id = {user_id}

            WHERE 1=1
                AND M.status = 'ok'
                AND R.meme_id IS NULL
                -- 100 ru, 50 en, 50 all lang
                AND M.id IN (4101086, 4442353, 3755262, 4524041, 914304, 1213657, 3477742, 3850309, 4106545, 3918656, 1976055, 3729527, 4370768, 4031941, 3902467, 3940729, 3966109, 4144377, 4131644, 4720051, 4438220, 943398, 3486879, 3958437, 3193252, 4011185, 3855063, 4261258, 4368086, 4255270, 1194244, 10222, 4818828, 3820043, 758408, 3188657, 4451345, 2050874, 4665040, 4106819, 3798967, 1825631, 3140601, 4840661, 4250457, 10202, 4363045, 3823857, 3755199, 4214428, 3604880, 3759401, 3928967, 3859587, 1240438, 4634391, 4002944, 2914449, 1955395, 1902244, 4256739, 1721327, 1285555, 1901653, 1584871, 3517077, 4493086, 4128512, 3570595, 3975285, 1484762, 1811655, 1071204, 4033401, 2294710, 4236782, 881987, 4180263, 1100991, 3867070, 1859048, 4285721, 1466518, 2262302, 4478289, 1859157, 4232654, 1202886, 978202, 2279188, 1892350, 961273, 4033397, 3513207, 3635346, 4320621, 4558947, 4252321, 1084225, 2350587, 4339982, 3724969, 3613758, 1768655, 4148626, 1285566, 2181541, 1103300, 3516406, 1197518, 4036174, 3537906, 2953444, 13636, 3724910, 3911502, 1988648, 3587199, 1398183, 4166913, 3911320, 1311422, 2153377, 3604881, 3596142, 1006843, 4473556, 4231678, 4856209, 10114, 3520485, 4232460, 1721545, 3747694, 3914292, 4119263, 4033399, 1482707, 4243473, 4336344, 1678337, 3516170, 2279191, 3724979, 3772372, 4763033, 4128276, 463991, 1006837, 1202853, 4101086, 1103300, 4119263, 4357615, 1194244, 3859587, 3630862, 4478289, 4665040, 3798967, 3940785, 10222, 4255187, 1304918, 3823857, 1398183, 16818, 881987, 2005796, 3639651, 4231648, 3902342, 4031503, 4231678, 4166913, 4720051, 3855063, 4370768, 2350587, 758408, 4818828, 4261258, 3587199, 648225, 4716664, 3918656, 4183519, 3600534, 4473556, 3772372, 4243473, 4524041, 943398, 4840661, 4250457, 1825631, 4363045, 4232460, 4148761, 3513207)
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY rand
            LIMIT {limit}
        ) M
    """
    res = await fetch_all(text(query))
    return res