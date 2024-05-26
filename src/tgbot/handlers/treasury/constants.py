from enum import Enum


class TrxType(str, Enum):
    MEME_UPLOADER = "meme_uploader"
    MEME_UPLOAD_REVIEWER = "meme_upload_reviewer"
    USER_INVITER = "user_inviter"
    USER_INVITER_PREMIUM = "user_inviter_premium"


PAYOUTS = {
    TrxType.MEME_UPLOADER: 5,
    TrxType.USER_INVITER: 5,
    TrxType.USER_INVITER_PREMIUM: 10,
    TrxType.MEME_UPLOAD_REVIEWER: 2,
}

# TODO: localize
TRX_TYPE_DESCRIPTIONS = {
    TrxType.MEME_UPLOADER: "uploading a meme",
    TrxType.USER_INVITER: "inviting a friend",
    TrxType.USER_INVITER_PREMIUM: "inviting a friend with premium",
    TrxType.MEME_UPLOAD_REVIEWER: "reviewing uploaded meme",
}
