import logging
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat


def draw_text_with_outline(
    draw: ImageDraw,
    position: tuple,
    text: str,
    font: ImageFont,
    text_colour: tuple,
    outline_colour: tuple,
) -> None:
    x, y = position
    # Draw outline
    for adj in range(-1, 2):
        for ops in range(-1, 2):
            # Avoid the center pixel
            if adj != 0 or ops != 0:
                draw.text((x + adj, y + ops), text, font=font, fill=outline_colour)
    draw.text(position, text, font=font, fill=text_colour)


def find_least_detailed_corner(img: Image, text_bbox: tuple, margin: int) -> tuple:
    """
    Find the corner in an image with mean intensity closest to black or white,
    indicating the least amount of detail. This is useful for identifying
    a suitable place to overlay text without obscuring important image details.

    Args:
    - img: A PIL.Image object representing the original image.
    - text_bbox: A tuple (x1, y1, x2, y2) specifying the bounding box
      where text will be placed.
    - margin: An integer or tuple specifying the margin size to consider
      around each corner.

    Returns:
    - A tuple (x, y) representing the top-left coordinate
        of the selected corner for text placement.
    """
    # Convert the original image to grayscale for intensity analysis
    gray_img = img.convert("L")
    img_w, img_h = img.size
    # Calculate the width and height of the text bounding box
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    # Define dictionary with the coordinates of each corner with some margin applied
    corners = {
        "top_left": (margin, margin),
        "top_right": (img_w - text_width - margin, margin),
        "bottom_left": (margin, img_h - text_height - margin),
        "bottom_right": (img_w - text_width - margin, img_h - text_height - margin),
    }
    # Initialize with infinity for comparison
    least_detailed_score = float("inf")
    # To store the x, y coordinates for watermark
    selected_corner = None
    selected_wm_colour = None
    # Iterate through each corner to find the one with the least detail background
    for _, (x, y) in corners.items():
        # Crop the image around the current corner
        # according to the text bounding box size
        sector = gray_img.crop((x, y, x + text_width, y + text_height))
        # Calculate mean intensity of the cropped area
        mean_intensity = ImageStat.Stat(sector).mean[0]
        # Determine how close the mean intensity is to either black (0) or white (255)
        # indicates how uniform the background of the selected sector is
        distance_to_extreme = min(abs(0 - mean_intensity), abs(255 - mean_intensity))
        # Update if this corner has a lower score (closer to black or white)
        if distance_to_extreme < least_detailed_score:
            least_detailed_score = distance_to_extreme
            selected_corner = (x, y)
            # Selecting watermark colour based on mean intensity
            selected_wm_colour = (0, 0, 0) if mean_intensity > 178 else (255, 255, 255)

    return selected_corner, selected_wm_colour


def check_font(font_path, font_family, image, width_ratio):
    fontsize = image.size[0] * width_ratio // 2
    font_file = Path(font_path) / font_family
    try:
        font = ImageFont.truetype(str(font_file), fontsize)
        logging.info(f"Loaded font from {font_file}.")
    except IOError:
        logging.error(f"Failed to load font from {font_file}.")
        raise

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
        text_position, text_colour = find_least_detailed_corner(base, text_bbox, margin)
        outline_colour = (
            (0, 0, 0, 255) if text_colour == (255, 255, 255) else (255, 255, 255, 255)
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
