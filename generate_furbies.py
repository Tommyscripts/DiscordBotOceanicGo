from PIL import Image, ImageDraw, ImageFont
import random
import os

OUT = os.path.join(os.path.dirname(__file__), "assets", "furbys")
os.makedirs(OUT, exist_ok=True)

colors = [(255, 182, 193), (173, 216, 230), (144, 238, 144), (255, 250, 205), (221,160,221), (240,230,140), (255,228,196), (176,224,230), (255,240,245), (224,255,255)]
faces = [":D", ":)", ":P", ":O", ":3", "^_^", "xD", "-_-", "<3", ":|"]

for i in range(1, 11):
    img = Image.new("RGBA", (400, 400), colors[(i-1) % len(colors)])
    draw = ImageDraw.Draw(img)
    # draw eyes
    rx = 30
    draw.ellipse((100-rx, 120-rx, 100+rx, 120+rx), fill=(255,255,255))
    draw.ellipse((300-rx, 120-rx, 300+rx, 120+rx), fill=(255,255,255))
    draw.ellipse((115-rx//2, 135-rx//2, 115+rx//2, 135+rx//2), fill=(0,0,0))
    draw.ellipse((315-rx//2, 135-rx//2, 315+rx//2, 135+rx//2), fill=(0,0,0))
    # mouth
    draw.ellipse((150, 250, 250, 300), fill=(255,182,193))
    # fluff
    for _ in range(60):
        x = random.randint(20, 380)
        y = random.randint(20, 380)
        r = random.randint(4, 12)
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(255,250,250,120))
    # text face
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except Exception:
        font = ImageFont.load_default()
    draw.text((160, 170), faces[(i-1) % len(faces)], fill=(0,0,0), font=font)
    path = os.path.join(OUT, f"furby_{i}.png")
    img.save(path)
    print("Saved", path)

print("Done generating furbies")
