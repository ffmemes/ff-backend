from src.flows.storage.describe_memes import VISION_MODELS


def test_describe_memes_vision_models_are_free_only():
    assert VISION_MODELS
    assert all(model_id.endswith(":free") for model_id in VISION_MODELS)


def test_describe_memes_does_not_use_removed_gemma_3_free_models():
    assert all("google/gemma-3-" not in model_id for model_id in VISION_MODELS)
