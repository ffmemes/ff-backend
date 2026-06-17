from src.flows.storage.openrouter_vision import VISION_MODELS


def test_describe_memes_vision_models_are_free_only():
    assert VISION_MODELS
    assert all(model_id.endswith(":free") for model_id in VISION_MODELS)


def test_describe_memes_does_not_use_removed_gemma_3_free_models():
    assert all("google/gemma-3-" not in model_id for model_id in VISION_MODELS)


def test_describe_memes_has_multiple_general_vision_fallbacks():
    assert "google/gemma-4-31b-it:free" in VISION_MODELS
    assert "nex-agi/nex-n2-pro:free" in VISION_MODELS
    assert "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free" in VISION_MODELS
    assert "nvidia/nemotron-3.5-content-safety:free" not in VISION_MODELS
    assert "nvidia/nemotron-nano-12b-v2-vl:free" not in VISION_MODELS
