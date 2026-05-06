import importlib.util
import sys
import types
from pathlib import Path


def load_sync_config(monkeypatch):
    monkeypatch.setenv("PAPERCLIP_URL", "https://paperclip.example")
    monkeypatch.setenv("PAPERCLIP_API_KEY", "test-key")
    monkeypatch.setenv("COMPANY_ID", "company-id")
    monkeypatch.setenv("SCRIPT_DIR", str(Path("agents").resolve()))

    module_path = Path("agents/_sync_config.py").resolve()
    module_name = "_sync_config_for_test"
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda _text: {}
    monkeypatch.setitem(sys.modules, "yaml", yaml_stub)

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_target_env_bindings_resolve_plain_secret_and_missing_required(monkeypatch):
    sync_config = load_sync_config(monkeypatch)

    cur_env = {
        "SENTRY_AUTH_TOKEN": {
            "type": "secret_ref",
            "secretId": "existing-token-secret",
            "version": "latest",
        },
    }
    target_inputs = {
        "env": {
            "OPENCLAW_SESSION": {"kind": "plain", "default": "1"},
            "PREFECT_API_URL": {"kind": "secret", "requirement": "required"},
            "SENTRY_AUTH_TOKEN": {"kind": "secret", "requirement": "required"},
            "SENTRY_ORG": {"kind": "secret", "requirement": "required"},
        }
    }

    bindings, missing = sync_config.target_env_bindings(
        cur_env,
        target_inputs,
        {"PREFECT_API_URL": "prefect-secret"},
    )

    assert bindings == {
        "OPENCLAW_SESSION": {"type": "plain", "value": "1"},
        "PREFECT_API_URL": {
            "type": "secret_ref",
            "secretId": "prefect-secret",
            "version": "latest",
        },
        "SENTRY_AUTH_TOKEN": {
            "type": "secret_ref",
            "secretId": "existing-token-secret",
            "version": "latest",
        },
    }
    assert missing == ["SENTRY_ORG"]


def test_merged_adapter_env_preserves_runtime_only_keys(monkeypatch):
    sync_config = load_sync_config(monkeypatch)

    cur_env = {
        "PATH": {"type": "plain", "value": "/paperclip/bin:/usr/bin"},
        "PREFECT_API_URL": {
            "type": "plain",
            "value": "http://65.108.127.32:4200/api",
        },
    }
    target_bindings = {
        "PREFECT_API_URL": {
            "type": "secret_ref",
            "secretId": "prefect-secret",
            "version": "latest",
        }
    }

    merged = sync_config.merged_adapter_env(cur_env, target_bindings)

    assert merged == {
        "PATH": {"type": "plain", "value": "/paperclip/bin:/usr/bin"},
        "PREFECT_API_URL": {
            "type": "secret_ref",
            "secretId": "prefect-secret",
            "version": "latest",
        },
    }


def test_adapter_env_changes_reports_added_and_changed_without_removing(monkeypatch):
    sync_config = load_sync_config(monkeypatch)

    cur_env = {
        "PATH": {"type": "plain", "value": "/paperclip/bin:/usr/bin"},
        "PREFECT_API_URL": {
            "type": "plain",
            "value": "http://65.108.127.32:4200/api",
        },
    }
    target_bindings = {
        "PREFECT_API_URL": {
            "type": "secret_ref",
            "secretId": "prefect-secret",
            "version": "latest",
        },
        "SENTRY_ORG": {
            "type": "secret_ref",
            "secretId": "sentry-org-secret",
            "version": "latest",
        },
    }

    assert sync_config.adapter_env_changes(cur_env, target_bindings) == [
        "+adapterConfig.env: ['SENTRY_ORG']",
        "~adapterConfig.env: ['PREFECT_API_URL']",
    ]
