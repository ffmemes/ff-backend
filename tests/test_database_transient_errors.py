import asyncpg
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.exc import DBAPIError

from src import database


def _dbapi_error_wrapping(exc: BaseException) -> DBAPIError:
    translated = AsyncAdapt_asyncpg_dbapi.Error(f"{type(exc)}: {exc}")
    try:
        raise translated from exc
    except Exception as wrapped:
        return DBAPIError.instance(
            "SELECT 1",
            {},
            wrapped,
            Exception,
            connection_invalidated=False,
            dialect=None,
        )


def test_stale_connection_error_matches_sqlalchemy_asyncpg_wrapper() -> None:
    exc = _dbapi_error_wrapping(asyncpg.exceptions.ConnectionDoesNotExistError("connection gone"))

    assert database._is_stale_connection_error(exc)


def test_concurrent_use_error_matches_raw_asyncpg_internal_client_error() -> None:
    exc = asyncpg.exceptions.InternalClientError(
        "cannot switch to state 15; another operation (2) is in progress"
    )

    assert database._is_concurrent_use_error(exc)


def test_concurrent_use_error_matches_sqlalchemy_asyncpg_wrapper() -> None:
    exc = _dbapi_error_wrapping(
        asyncpg.exceptions.InternalClientError(
            "cannot switch to state 15; another operation (2) is in progress"
        )
    )

    assert database._is_concurrent_use_error(exc)


def test_internal_client_error_without_concurrent_operation_is_not_transient() -> None:
    exc = asyncpg.exceptions.InternalClientError("unexpected protocol state")

    assert not database._is_concurrent_use_error(exc)


def test_deadlock_error_matches_sqlalchemy_asyncpg_wrapper() -> None:
    exc = _dbapi_error_wrapping(asyncpg.exceptions.DeadlockDetectedError("deadlock detected"))

    assert database._is_deadlock_error(exc)


def test_handle_error_marks_wrapped_concurrent_use_as_disconnect() -> None:
    class Context:
        original_exception = _dbapi_error_wrapping(
            asyncpg.exceptions.InternalClientError(
                "cannot switch to state 15; another operation (2) is in progress"
            )
        )
        is_disconnect = False

    context = Context()

    database._mark_bad_connection_as_disconnect(context)

    assert context.is_disconnect
