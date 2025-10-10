"""Script de prueba para generar la GIF de la ruleta localmente sin Discord.
Genera un GIF sencillo usando la misma lógica de dibujo de `bot.py`.
"""
from PIL import Image, ImageDraw, ImageFont
import math
import random
import os
import time

def generate_wheel(names, winner_index, out_dir):
    size = 400
    center = size // 2
    num = len(names)
    colors = [
        (255,99,71),(60,179,113),(65,105,225),(238,130,238),(255,215,0),(70,130,180),
        (255,165,0),(144,238,144),(199,21,133),(30,144,255),(218,165,32),(152,251,152)
    ]
    base = Image.new("RGBA", (size, size), (255,255,255,0))
    bdraw = ImageDraw.Draw(base)
    bbox = (10, 10, size-10, size-10)
    bdraw.ellipse(bbox, fill=(240,240,240), outline=(0,0,0))

    for i, nm in enumerate(names):
        start_angle = 360.0 * i / num
        end_angle = 360.0 * (i+1) / num
        color = colors[i % len(colors)]
        bdraw.pieslice(bbox, start=-start_angle, end=-end_angle, fill=color, outline=(255,255,255))

    center_radius = 40
    bdraw.ellipse((center-center_radius, center-center_radius, center+center_radius, center+center_radius), fill=(255,255,255), outline=(0,0,0))

    labels = Image.new("RGBA", (size, size), (255,255,255,0))
    ldraw = ImageDraw.Draw(labels)
    try:
        base_font_size = max(10, int(90 / max(4, num)))
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", base_font_size)
    except Exception:
        font = ImageFont.load_default()

    for i, nm in enumerate(names):
        start_angle = 360.0 * i / num
        end_angle = 360.0 * (i+1) / num
        mid_angle = (start_angle + end_angle) / 2
        r = int((size/2 - 30) * 0.8)
        theta = (mid_angle) * (math.pi/180.0)
        tx = int(center + r * -math.sin(theta))
        ty = int(center + r * -math.cos(theta))
        text = nm
        if len(text) > 12:
            text = text[:11] + "…"
        # robust text size
        try:
            bbox = ldraw.textbbox((0,0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            try:
                tw, th = font.getsize(text)
            except Exception:
                try:
                    bbox2 = font.getbbox(text)
                    tw = bbox2[2] - bbox2[0]
                    th = bbox2[3] - bbox2[1]
                except Exception:
                    tw, th = (0,0)
        ldraw.text((tx - tw//2, ty - th//2), text, font=font, fill=(0,0,0))

    wheel_img = Image.alpha_composite(base, labels)

    target_mid = (360.0 * winner_index / num + 360.0 * (winner_index+1) / num) / 2
    target_rotation = -target_mid
    start_rotation = random.uniform(0, 360)
    total_turns = random.uniform(2, 4)
    final_rotation = start_rotation + total_turns * 360 + target_rotation

    frames = []
    frame_count = 24
    for f in range(frame_count):
        t = f / (frame_count - 1)
        ease = 1 - pow(1 - t, 3)
        rot = start_rotation + (final_rotation - start_rotation) * ease
        frame = wheel_img.rotate(rot, resample=Image.BICUBIC, center=(center, center))
        canvas = Image.new("RGBA", (size, size+40), (255,255,255,255))
        canvas.paste(frame, (0,0), frame)
        cdraw = ImageDraw.Draw(canvas)
        pointer = [(center-12, 4), (center+12, 4), (center, 30)]
        cdraw.polygon(pointer, fill=(30,30,30))
        frames.append(canvas.convert("P"))

    # final label
    try:
        font_sm = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
    except Exception:
        font_sm = ImageFont.load_default()
    winner_text = f"Winner: {names[winner_index]}"
    final = frames[-1].convert("RGBA")
    fdraw = ImageDraw.Draw(final)
    try:
        bbox = fdraw.textbbox((0,0), winner_text, font=font_sm)
        wtw = bbox[2] - bbox[0]
        wth = bbox[3] - bbox[1]
    except Exception:
        try:
            wtw, wth = font_sm.getsize(winner_text)
        except Exception:
            try:
                bbox2 = font_sm.getbbox(winner_text)
                wtw = bbox2[2] - bbox2[0]
                wth = bbox2[3] - bbox2[1]
            except Exception:
                wtw, wth = (0,0)
    fdraw.rectangle(((size- wtw)//2 - 8, size - 40, (size+wtw)//2 + 8, size - 8), fill=(255,255,255,200))
    fdraw.text(((size-wtw)/2, size-36), winner_text, fill=(0,0,0), font=font_sm)
    frames[-1] = final.convert("P")

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"wheel_test_{int(time.time())}.gif")
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=120, loop=0, optimize=False)
    return out_path

if __name__ == '__main__':
    names = ["Ana", "Borja", "Carlos", "Diana", "Emma", "Felix"]
    winner_index = random.randrange(len(names))
    out = generate_wheel(names, winner_index, os.path.join(os.path.dirname(__file__), '..', '.temp'))
    print('Generated GIF at', out)
