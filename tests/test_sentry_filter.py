from src.main import _filter_expected_sentry_events


def test_sentry_filter_drops_expected_chat_agent_max_turns_event():
    event = {
        "exception": {
            "values": [
                {
                    "type": "MaxTurnsExceeded",
                    "module": "agents.exceptions",
                }
            ]
        }
    }

    assert _filter_expected_sentry_events(event, {}) is None


def test_sentry_filter_keeps_unexpected_events():
    event = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "module": "builtins",
                }
            ]
        }
    }

    assert _filter_expected_sentry_events(event, {}) is event
