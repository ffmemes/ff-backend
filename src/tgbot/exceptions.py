class BaseFFMemesException(Exception):
    BASE_DETAIL = "Base FastFoodMemes Exception"

    def __init__(self, *args) -> None:
        super().__init__(*args if args else self.BASE_DETAIL)


class NoUserInfoFound(BaseFFMemesException):
    DETAIL = "No user info found in database."

    def __init__(self, user_id: int) -> None:
        super().__init__(f"Can't get_user_info({user_id}). Probably no data in db.")
