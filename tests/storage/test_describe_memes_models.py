import ast
from pathlib import Path


def _vision_models() -> list[str]:
    tree = ast.parse(Path("src/flows/storage/describe_memes.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VISION_MODELS":
                    return ast.literal_eval(node.value)
    raise AssertionError("VISION_MODELS assignment not found")


def test_vision_models_are_free_only():
    assert all(model.endswith(":free") for model in _vision_models())


def test_removed_openrouter_vision_models_are_not_used():
    models = _vision_models()

    assert "google/gemma-3-27b-it:free" not in models
    assert "google/gemma-3-12b-it:free" not in models
    assert "nvidia/nemotron-nano-12b-v2-vl:free" not in models
