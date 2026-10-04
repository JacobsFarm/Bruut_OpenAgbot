import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT_PATHS = (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf")


def load_font(size):
    for path in FONT_PATHS:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def nl(value, decimals=1):
    return ("%.*f" % (decimals, value)).replace(".", ",")


def caption(meta):
    return [
        "snelheid %s m/s" % nl(meta["v"] / 1000.0),
        "koers %s\u00b0" % nl(math.degrees(meta["psi"]), 0),
        "stuurhoek links %s\u00b0   rechts %s\u00b0" % (nl(math.degrees(meta["dl"])), nl(math.degrees(meta["dr"]))),
    ]


def decorate(image, meta, font):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    lines = caption(meta)
    pad = 8
    line_h = font.size + 4
    width = max(draw.textlength(line, font=font) for line in lines) + 2 * pad
    draw.rounded_rectangle((10, 10, 10 + width, 10 + line_h * len(lines) + 2 * pad - 4), radius=8, fill=(255, 255, 255, 215))
    for i, line in enumerate(lines):
        draw.text((10 + pad, 10 + pad + i * line_h), line, fill=(30, 30, 30, 255), font=font)
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def main(folder, out_path, fps=15, last_hold_ms=1500):
    with open(os.path.join(folder, "frames.json"), encoding="utf-8") as handle:
        metas = json.load(handle)
    names = sorted(n for n in os.listdir(folder) if n.startswith("frame_") and n.endswith(".png"))
    font = load_font(17)
    images = [decorate(Image.open(os.path.join(folder, n)), metas[int(n[6:10])], font) for n in names]

    sample = [images[i] for i in range(0, len(images), max(1, len(images) // 10))]
    sheet = Image.new("RGB", (images[0].width, images[0].height * len(sample)))
    for i, im in enumerate(sample):
        sheet.paste(im, (0, i * images[0].height))
    palette = sheet.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)

    frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    durations = []
    previous = 0
    for i in range(len(frames)):
        current = int(round((i + 1) * 1000.0 / fps / 10.0)) * 10
        durations.append(current - previous)
        previous = current
    durations[-1] = last_hold_ms
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)
    print("%d frames -> %s (%.2f MB)" % (len(frames), out_path, os.path.getsize(out_path) / 1e6))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 15)
