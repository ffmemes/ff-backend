import base64
from types import SimpleNamespace

import pytest

from src.comms.image_generation import (
    DEFAULT_IMAGE_MODEL,
    build_editorial_image_prompt,
    generate_editorial_image,
)


class _FakeImages:
    def __init__(self):
        self.kwargs = None

    async def generate(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(b"png-bytes").decode("ascii"),
                    revised_prompt="revised prompt",
                )
            ]
        )


class _FakeClient:
    def __init__(self):
        self.images = _FakeImages()


def test_build_editorial_image_prompt_is_precise_and_brand_safe():
    prompt = build_editorial_image_prompt(
        post_text="Интересное: пользователи стали дольше сидеть в боте.",
        visual_brief="One glowing feed card pulls attention while background cards fade.",
        composition="Centered phone-like feed stack, one warm orange signal line.",
    )

    assert "Post context:" in prompt
    assert "Visual brief:" in prompt
    assert "#FF6B35" in prompt
    assert "Do not include readable text" in prompt
    assert "apolitical" in prompt


@pytest.mark.asyncio
async def test_generate_editorial_image_returns_bytes_and_uses_gpt_image_2():
    client = _FakeClient()
    image = await generate_editorial_image("make image", client=client)

    assert image.image_bytes == b"png-bytes"
    assert image.revised_prompt == "revised prompt"
    assert image.model == DEFAULT_IMAGE_MODEL
    assert client.images.kwargs["model"] == "gpt-image-2"
    assert client.images.kwargs["output_format"] == "png"
    assert client.images.kwargs["n"] == 1


@pytest.mark.asyncio
async def test_generate_editorial_image_rejects_empty_response():
    class EmptyImages:
        async def generate(self, **kwargs):
            return SimpleNamespace(data=[])

    client = SimpleNamespace(images=EmptyImages())

    with pytest.raises(RuntimeError, match="no images"):
        await generate_editorial_image("make image", client=client)
