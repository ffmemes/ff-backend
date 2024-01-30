from pathlib import Path
import random
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def draw_text_with_outline(draw, position, text, font, text_colour, outline_colour):
    x, y = position
    # Draw outline
    for adj in range(-1, 2):
        for ops in range(-1, 2):
            if adj != 0 or ops != 0:  # Avoid the center pixel
                draw.text((x+adj, y+ops), text, font=font, fill=outline_colour)
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
        (img_w - text_width - margin, img_h - text_height - margin)  # Bottom-right
    ]

    return corners

def check_font_size(text, font_path, image, width_ratio):
    breakpoint = width_ratio * image.size[0]
    fontsize = 20
    learning_rate = 5
    font = ImageFont.truetype(font_path, fontsize)
    while True:
        if font.getlength(text) < breakpoint:
            fontsize += learning_rate
        else:
            learning_rate = learning_rate // 2
            fontsize -= learning_rate
        font = ImageFont.truetype(font_path, fontsize)
        if learning_rate <= 1:
            break
    return font

def draw_corner_watermark(
    image_bytes: BytesIO,
    text: str,
    font_family: str = "Gidole-Regular.ttf",
    margin: int = 24
) -> Image:
    with Image.open(image_bytes).convert("RGBA") as base:
        txt = Image.new("RGBA", base.size, (255, 255, 255, 0))
        
        d = ImageDraw.Draw(txt)

        width_ratio = .15  # Portion of the image the text width should be (between 0 and 1)
        font_path = str(Path(Path.home(), "src", "fonts", font_family))
        fnt = check_font_size(text, font_path, base, width_ratio)
        # fnt = ImageFont.load_default()
        # calculate size of textbox
        text_bbox = d.textbbox((0, 0), text, font=fnt)
        # choose a random corner for the text
        corners = calculate_corners(img_w=base.size[0], img_h=base.size[1], text_bbox=text_bbox, margin=margin)
        text_position = random.choice(corners)
        # text_position = choice(calculate_corners(img_w=base.size[0], img_h=base.size[1], text_bbox=text_bbox, margin=margin))
        # average brightness of pixel check and switch between black/white
        base_brightness = sum(base.getpixel(text_position)[:3]) / 3
        text_colour = select_wm_colour(base_brightness)
        # define outline colour (opposite of text colour for contrast)
        outline_colour = (0, 0, 0, 255) if text_colour == (255, 255, 255, 255) else (255, 255, 255, 255)
        draw_text_with_outline(d, text_position, text, fnt, text_colour, outline_colour)
        # overlay image of each other
        return Image.alpha_composite(base, txt).convert('RGB')


# TODO: async?
def add_watermark(image_content: bytes) -> BytesIO | None:
    image_bytes = BytesIO(image_content)

    try:
        image = draw_corner_watermark(
            image_bytes,
            text='@ffmemesbot',
            text_size=18,
            margin=20
        )
    except Exception as e:
        print(f'Error while adding watermark: {e}')
        return None

    buff = BytesIO()
    buff.name = 'image_x.jpeg'
    image.save(buff, 'JPEG')
    buff.seek(0)

    return buff#image

# if __name__ == '__main__':
    
#     # image_path = Path(Path.home(), "src", "test1.jpeg")  # Adjust the path if necessary
#     image_path = Path(Path.home(), "src", "test1.jpeg")  # Adjust the path if necessary
#     with open(image_path, 'rb') as image_file:
#         image_bytes = image_file.read()
#     watermarked_image = add_watermark(image_bytes)
#     watermarked_image.save('/src/image_3x.jpg')
   