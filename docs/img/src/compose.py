from PIL import Image, ImageDraw, ImageFilter
import sys
def phone(path, w=560):
    im = Image.open(path).convert("RGB")
    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    r = 44
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, fill=255)
    out = Image.new("RGBA", im.size); out.paste(im, (0, 0), mask)
    border = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, outline=(128, 128, 128, 110), width=3)
    return Image.alpha_composite(out, border)
def sheet(paths, out, gap=48, pad=24):
    ps = [phone(p) for p in paths]
    W = sum(p.width for p in ps) + gap * (len(ps) - 1) + 2 * pad
    H = max(p.height for p in ps) + 2 * pad
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = pad
    for p in ps:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((x + 4, pad + 10, x + p.width + 4, pad + p.height + 10), 44, fill=(0, 0, 0, 70))
        canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(10)))
        canvas.alpha_composite(p, (x, pad)); x += p.width + gap
    canvas.save(out)
sheet(sys.argv[2:], sys.argv[1])
