import logging
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat


def draw_text_with_outline(draw, position, text, font, text_colour, outline_colour):
    x, y = position
    # Draw outline
    for adj in range(-1, 2):
        for ops in range(-1, 2):
            # Avoid the center pixel
            if adj != 0 or ops != 0:
                draw.text((x + adj, y + ops), text, font=font, fill=outline_colour)
    draw.text(position, text, font=font, fill=text_colour)


def select_wm_colour(base, text_position) -> tuple:
    # average brightness of pixel check and switch between black/white
    base_brightness = sum(base.getpixel(text_position)[:3]) / 3
    # if base_brightness > 128:
    if base_brightness > 178:
        # Black text for lighter background
        text_colour = (0, 0, 0, 255)
    else:
        # White text for darker background
        text_colour = (255, 255, 255, 255)

    return text_colour


def find_least_detailed_corner(img, text_bbox, margin):
    gray_img = img.convert("L")  # Convert image to grayscale

    img_w, img_h = img.size
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    corners = [
        (margin, margin, margin + text_width, margin + text_height),  # Top-left
        (
            img_w - text_width - margin,
            margin,
            img_w - margin,
            margin + text_height,
        ),  # Top-right
        (
            margin,
            img_h - text_height - margin,
            margin + text_width,
            img_h - margin,
        ),  # Bottom-left
        (
            img_w - text_width - margin,
            img_h - text_height - margin,
            img_w - margin,
            img_h - margin,
        ),  # Bottom-right
    ]

    min_detail = float("inf")
    selected_corner = None

    for corner in corners:
        sector = gray_img.crop(corner)
        stat = ImageStat.Stat(sector)
        mean = stat.mean[0]  # Mean pixel value in the sector
        w_border, b_border = 255, 0
        min_diff_for_corner = min(abs(mean - w_border), abs(mean - b_border))

        if min_diff_for_corner < min_detail:
            min_detail = min_diff_for_corner
            selected_corner = corner[:2]  # Keep only the starting coordinates
    return selected_corner


def check_font(font_path, font_family, image, width_ratio):
    fontsize = image.size[0] * width_ratio // 2
    font_file = Path(font_path) / font_family
    font = ImageFont.truetype(str(font_file), fontsize)

    logging.info(f"Loaded font from {font_file}.")
    return font


def draw_corner_watermark(
    image_bytes: BytesIO,
    text: str,
    font_family: str = "WorkSans-Medium.ttf",
    width_ratio: float = 0.05,
    text_opacity: float = 0.35,
    margin: int = 5,
) -> Image:
    with Image.open(image_bytes).convert("RGBA") as base:
        txt = Image.new("RGBA", base.size, (255, 255, 255, 0))
        d = ImageDraw.Draw(txt)
        fonts_files_dir = Path(__file__).parent.parent.parent / "static/fonts"
        font = check_font(fonts_files_dir, font_family, base, width_ratio)
        text_bbox = d.textbbox((0, 0), text, font=font)
        text_position = find_least_detailed_corner(base, text_bbox, margin)
        text_colour = select_wm_colour(base, text_position)
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
