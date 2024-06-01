from enum import Enum


class TrxType(str, Enum):
    MEME_UPLOADER = "meme_uploader"
    MEME_UPLOAD_REVIEWER = "meme_upload_reviewer"
    USER_INVITER = "user_inviter"
    USER_INVITER_PREMIUM = "user_inviter_premium"

    UPLOADER_TOP_WEEKLY_1 = "uploader_top_weekly_1"
    UPLOADER_TOP_WEEKLY_2 = "uploader_top_weekly_2"
    UPLOADER_TOP_WEEKLY_3 = "uploader_top_weekly_3"
    UPLOADER_TOP_WEEKLY_4 = "uploader_top_weekly_4"
    UPLOADER_TOP_WEEKLY_5 = "uploader_top_weekly_5"


PAYOUTS = {
    TrxType.MEME_UPLOADER: 5,
    TrxType.USER_INVITER: 10,
    TrxType.USER_INVITER_PREMIUM: 20,
    TrxType.MEME_UPLOAD_REVIEWER: 1,
    TrxType.UPLOADER_TOP_WEEKLY_1: 500,
    TrxType.UPLOADER_TOP_WEEKLY_2: 300,
    TrxType.UPLOADER_TOP_WEEKLY_3: 200,
    TrxType.UPLOADER_TOP_WEEKLY_4: 100,
    TrxType.UPLOADER_TOP_WEEKLY_5: 50,
}

# TODO: localize
TRX_TYPE_DESCRIPTIONS = {
    TrxType.MEME_UPLOADER: "uploading a meme",
    TrxType.USER_INVITER: "inviting a friend",
    TrxType.USER_INVITER_PREMIUM: "inviting a friend with premium",
    TrxType.MEME_UPLOAD_REVIEWER: "reviewing uploaded meme",
    TrxType.UPLOADER_TOP_WEEKLY_1: "weekly top 1 meme",
    TrxType.UPLOADER_TOP_WEEKLY_2: "weekly top 2 meme",
    TrxType.UPLOADER_TOP_WEEKLY_3: "weekly top 3 meme",
    TrxType.UPLOADER_TOP_WEEKLY_4: "weekly top 4 meme",
    TrxType.UPLOADER_TOP_WEEKLY_5: "weekly top 5 meme",
}
