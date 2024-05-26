from typing import Dict, List

from sqlalchemy import text

from src.database import fetch_all
from src.recommendations.utils import exclude_meme_ids_sql_filter


async def get_random_best(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
):
    """Selects 'limit' best memes from the top 100 memes obtained using the cleared
    meme statistics. The cleared statistics aggregates reactions from users with
    less than 200 previous reactions. It's aim is to remove the bias from old users
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
                AND M.id IN (
                    4101086, 4442353, 3755262, 4524041, 914304, 1213657,
                    3477742, 3850309, 4106545, 3918656, 1976055, 3729527,
                    4370768, 4031941, 3902467, 3940729, 3966109, 4144377,
                    4131644, 4720051, 4438220, 943398, 3486879, 3958437,
                    3193252, 4011185, 3855063, 4261258, 4368086, 4255270,
                    1194244, 10222, 4818828, 3820043, 758408, 3188657,
                    4451345, 2050874, 4665040, 4106819, 3798967, 1825631,
                    3140601, 4840661, 4250457, 10202, 4363045, 3823857,
                    3755199, 4214428, 3604880, 3759401, 3928967, 3859587,
                    1240438, 4634391, 4002944, 2914449, 1955395, 1902244,
                    4256739, 1721327, 1285555, 1901653, 1584871, 3517077,
                    4493086, 4128512, 3570595, 3975285, 1484762, 1811655,
                    1071204, 4033401, 2294710, 4236782, 881987, 4180263,
                    1100991, 3867070, 1859048, 4285721, 1466518, 2262302,
                    4478289, 1859157, 4232654, 1202886, 978202, 2279188,
                    1892350, 961273, 4033397, 3513207, 3635346, 4320621,
                    4558947, 4252321, 1084225, 2350587, 4339982, 3724969,
                    3613758, 1768655, 4148626, 1285566, 2181541, 1103300,
                    3516406, 1197518, 4036174, 3537906, 2953444, 13636,
                    3724910, 3911502, 1988648, 3587199, 1398183, 4166913,
                    3911320, 1311422, 2153377, 3604881, 3596142, 1006843,
                    4473556, 4231678, 4856209, 10114, 3520485, 4232460,
                    1721545, 3747694, 3914292, 4119263, 4033399, 1482707,
                    4243473, 4336344, 1678337, 3516170, 2279191, 3724979,
                    3772372, 4763033, 4128276, 463991, 1006837, 1202853,
                    4101086, 1103300, 4119263, 4357615, 1194244, 3859587,
                    3630862, 4478289, 4665040, 3798967, 3940785, 10222,
                    4255187, 1304918, 3823857, 1398183, 16818, 881987,
                    2005796, 3639651, 4231648, 3902342, 4031503, 4231678,
                    4166913, 4720051, 3855063, 4370768, 2350587, 758408,
                    4818828, 4261258, 3587199, 648225, 4716664, 3918656,
                    4183519, 3600534, 4473556, 3772372, 4243473, 4524041,
                    943398, 4840661, 4250457, 1825631, 4363045, 4232460,
                    4148761, 3513207
                )
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY rand
            LIMIT {limit}
        ) M
    """
    res = await fetch_all(text(query))
    return res


async def get_selected_sources(
    user_id: int,
    limit: int = 10,
    exclude_meme_ids: list[int] = [],
) -> List[Dict]:
    """Implements a test version of an algotighm which takes best memes from
    some selected sources
    """

    query_lang = f"""
        SELECT language_code
        FROM user_language
        WHERE user_id = {user_id}
    """

    res = await fetch_all(text(query_lang))
    if not len(res):
        return []
    print(res)
    is_lang_ru_en = all([row["language_code"] in ("ru", "en") for row in res])

    if not is_lang_ru_en:
        return []

    query = f"""
        SELECT
            M.id
            , M.type, M.telegram_file_id, M.caption, M.recommended_by
        FROM (
            SELECT
                M.id
                , M.type, M.telegram_file_id, M.caption
                , 'selected_sources_240513' AS recommended_by
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
                AND M.id IN (
                    12632, 2687384, 4691317, 7800835, 7263240,
                    7800833, 7273747, 5594231, 1190355, 7313587,
                    7737207, 121592, 5762991, 1173406, 6393105,
                    6470439, 7648698, 6522792, 7746601, 1023569,
                    121513, 6680926, 7003156, 2163445, 7728617,
                    3855063, 6305615, 7564457, 6953202, 2341860,
                    7462187, 7650435, 6691124, 7425200, 7800853,
                    5688394, 7309298, 7743723, 130092, 6494305,
                    6931153, 1173405, 2744097, 1976242, 1220485,
                    3530822, 1017007, 5903961, 7398465, 6952525,
                    285571, 6965529, 7510581, 2010680, 2086971,
                    1573399, 6902677, 7264007, 6623571, 7515039,
                    5111892, 7527928, 7186939, 7341028, 6606148,
                    7234885, 7447514, 12684, 7118266, 6690818,
                    7797882, 7570548, 5439952, 6452942, 7532191,
                    5048161, 1190740, 7109188, 12664, 6611543,

                    6965529, 6930231, 5605642, 4047586, 6902689,
                    7820185, 6663230
                )
                {exclude_meme_ids_sql_filter(exclude_meme_ids)}
            ORDER BY rand
            LIMIT {limit}
        ) M
    """
    res = await fetch_all(text(query))
    return res
