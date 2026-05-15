from src.observability.sentry import (
    before_send_log,
    sentry_log_extra,
    user_upload_observability_context,
)
from src.storage.constants import MemeStatus, MemeType


def test_user_upload_observability_context_keeps_safe_upload_facts_without_file_ids():
    context = user_upload_observability_context(
        {
            "id": 101,
            "type": MemeType.IMAGE,
            "status": MemeStatus.CREATED,
            "language_code": "ru",
            "telegram_file_id": "raw-telegram-file-id",
        },
        {
            "id": 202,
            "user_id": 303,
            "message_id": 404,
            "language_code": "ru",
            "forward_origin": {"type": "user", "sender_user": {"id": 1}},
            "media": {
                "file_id": "raw-file-id",
                "file_unique_id": "raw-file-unique-id",
                "file_size": 12345,
                "mime_type": "image/jpeg",
                "width": 800,
                "height": 600,
            },
        },
    )

    assert context["meme"] == {
        "id": 101,
        "type": "image",
        "status": "created",
        "language_code": "ru",
        "has_telegram_file_id": True,
    }
    assert context["user_upload"] == {
        "upload_id": 202,
        "user_id": 303,
        "message_id": 404,
        "language_code": "ru",
        "forward_origin_type": "user",
    }
    assert context["telegram_media"] == {
        "file_size": 12345,
        "mime_type": "image/jpeg",
        "duration": None,
        "width": 800,
        "height": 600,
    }


def test_sentry_log_extra_flattens_safe_context_and_filters_secret_values():
    extra = sentry_log_extra(
        {
            "user_upload": {
                "upload_id": 202,
                "user_id": 303,
                "bot_token": "secret",
            }
        },
        phase="upload_to_storage",
        sentry_dsn="secret",
    )

    assert extra == {
        "ff_user_upload_upload_id": 202,
        "ff_user_upload_user_id": 303,
        "ff_phase": "upload_to_storage",
    }


def test_before_send_log_scrubs_searchable_attributes_and_truncates_body():
    log = {
        "body": "x" * 2100,
        "attributes": {
            "ff_user_upload_upload_id": 202,
            "authorization": "Bearer secret",
        },
    }

    scrubbed = before_send_log(log, {})

    assert scrubbed is log
    assert scrubbed["attributes"]["ff_user_upload_upload_id"] == 202
    assert scrubbed["attributes"]["authorization"] == "[Filtered]"
    assert len(scrubbed["body"]) < 2100
    assert scrubbed["body"].endswith("...[truncated]")
