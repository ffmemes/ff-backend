import random
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageStat


def select_wm_colour(base_brightness) -> tuple:
    if base_brightness > 128:
        # Black text for lighter background
        text_colour = (0, 0, 0, 255)
    else:
        # White text for darker background
        text_colour = (255, 255, 255, 255)
    
    return text_colour


def calculate_corners(img_w: int, img_h: int, text_bbox: tuple, margin: int=10) -> list:
    # this piece of shit (code) just for estimate size of text 
    # the (0, 0) is the starting position. return tuple (x1, y1, x2, y2)
    
    margin = 10
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Choose a random corner for the text
    corners = [
        (margin, margin),  # Top-left
        (img_w - text_width - margin, margin),  # Top-right
        (margin, img_h - text_height - margin),  # Bottom-left
        (img_w - text_width - margin, img_h - text_height - margin)  # Bottom-right
    ]

    return corners


def draw_corner_watermark(image_content: bytes, text: str, text_size: int):
    image_bytes = BytesIO(image_content)

    with Image.open(image_bytes).convert("RGBA") as base:
        txt = Image.new("RGBA", base.size, (255, 255, 255, 0))
        fnt = ImageFont.truetype(font="Georgia.ttf", size=text_size)
        d = ImageDraw.Draw(txt)

        margin = 10
        # calculate size of textbox
        text_bbox = d.textbbox((0, 0), text, font=fnt)
        # Choose a random corner for the text
        corners = calculate_corners(img_w=base.size[0], img_h=base.size[1], text_bbox=text_bbox, margin=margin)
        text_position = random.choice(corners)
        # average brightness of pixel cheeeeck and switch between black/white
        base_brightness = sum(base.getpixel(text_position)[:3]) / 3
        text_colour = select_wm_colour(base_brightness)
        d.text(text_position, text, font=fnt, fill=text_colour)
        # overlay image of each other
        out = Image.alpha_composite(base, txt)
        return out


# TODO: async?
def add_watermark(image_content: bytes):
    return draw_corner_watermark(
        image_content,
        text='@ffmemesbot',
        text_size=18,
    )