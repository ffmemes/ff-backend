import logging
import random
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def draw_text_with_outline(draw, position, text, font, text_colour, outline_colour):
    x, y = position
    # Draw outline
    for adj in range(-1, 2):
        for ops in range(-1, 2):
            # Avoid the center pixel
            if adj != 0 or ops != 0:
                draw.text((x + adj, y + ops), text, font=font, fill=outline_colour)
    draw.text(position, text, font=font, fill=text_colour)


def select_wm_colour(base_brightness) -> tuple:
    # if base_brightness > 128:
    if base_brightness > 178:
        # Black text for lighter background
        text_colour = (0, 0, 0, 255)
    else:
        # White text for darker background
        text_colour = (255, 255, 255, 255)

    return text_colour


def calculate_corners(img_w, img_h, text_bbox, margin) -> list:
    # Estimate text size rely on font and text box
    # the (0, 0) is the starting position. return tuple (x1, y1, x2, y2)

    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    # Choose a random corner for the text
    corners = [
        (margin, margin),  # Top-left
        (img_w - text_width - margin, margin),  # Top-right
        (margin, img_h - text_height - margin),  # Bottom-left
        (img_w - text_width - margin, img_h - text_height - margin),  # Bottom-right
    ]

    return corners


def check_font(font_path, font_family, image, width_ratio):
    fontsize = image.size[0] * width_ratio // 2
    font_file = Path(font_path) / font_family
    font = ImageFont.truetype(str(font_file), fontsize)

    logging.info(f"Loaded font from {font_file}.")
    return font


def draw_corner_watermark(
    image_bytes: BytesIO,
    text: str,
    font_family: str = "Switzer-Variable.ttf",
    width_ratio: float = 0.07,
    text_opacity: float = 0.7,
    margin: int = 20,
) -> Image:
    with Image.open(image_bytes).convert("RGBA") as base:
        txt = Image.new("RGBA", base.size, (255, 255, 255, 0))

        d = ImageDraw.Draw(txt)
        # ratio of text on the image
        fonts_files_dir = Path(__file__).parent.parent.parent / "static/fonts"
        font = check_font(fonts_files_dir, font_family, base, width_ratio)
        # calculate size of textbox
        text_bbox = d.textbbox((0, 0), text, font=font)
        # choose a random corner for the text
        corners = calculate_corners(
            img_w=base.size[0], img_h=base.size[1], text_bbox=text_bbox, margin=margin
        )
        text_position = random.choice(corners)
        # average brightness of pixel check and switch between black/white
        base_brightness = sum(base.getpixel(text_position)[:3]) / 3
        text_colour = select_wm_colour(base_brightness)
        # define outline colour (opposite of text colour for contrast)
        outline_colour = (
            (0, 0, 0, 255)
            if text_colour == (255, 255, 255, 255)
            else (255, 255, 255, 255)
        )
        draw_text_with_outline(
            d, text_position, text, font, text_colour, outline_colour
        )
        # text opacity
        txt.putalpha(txt.getchannel("A").point(lambda x: x * text_opacity))
        # overlay image of each other
        return Image.alpha_composite(base, txt).convert("RGB")


# TODO: async?
def add_watermark(image_content: bytes) -> BytesIO | None:
    image_bytes = BytesIO(image_content)

    try:
        image = draw_corner_watermark(image_bytes, text="@ffmemesbot")
    except Exception as e:
        print(f"Error while adding watermark: {e}")
        return None

    buff = BytesIO()
    buff.name = "image.jpeg"
    image.save(buff, "JPEG")
    buff.seek(0)

    return buff
