from enum import Enum


class TrxType(str, Enum):
    MEME_UPLOADER = "meme_uploader"
    USER_INVITER = "user_inviter"
    USER_INVITER_PREMIUM = "user_inviter_premium"


PAYOUTS = {
    TrxType.MEME_UPLOADER: 5,
    TrxType.USER_INVITER: 5,
    TrxType.USER_INVITER_PREMIUM: 10,
}

# TODO: localize
TRX_TYPE_DESCRIPTIONS = {
    TrxType.MEME_UPLOADER: "uploading a meme",
    TrxType.USER_INVITER: "inviting a friend",
    TrxType.USER_INVITER_PREMIUM: "inviting a friend with premium",
}
