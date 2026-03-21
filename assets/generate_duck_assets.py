"""
Simple script to generate placeholder PNG assets for the duck game.
Run this once to create the required images in the `assets/` folder.
"""
from PIL import Image, ImageDraw

OUTPUTS = {
    "duck_base.png": (256, 256),
    "duck_helmet.png": (256, 256),
    "duck_sword.png": (256, 256),
    "duck_shield.png": (256, 256),
}

def create_duck_base(path, size):
    img = Image.new("RGBA", size, (0,0,0,0))
    draw = ImageDraw.Draw(img)
    # body
    draw.ellipse((32, 48, 224, 208), fill=(255,220,0,255))
    # eye
    draw.ellipse((170, 92, 190, 112), fill=(0,0,0,255))
    # beak
    draw.polygon([(220,130),(240,120),(220,100)], fill=(255,140,0,255))
    img.save(path)

def create_helmet(path, size):
    img = Image.new("RGBA", size, (0,0,0,0))
    draw = ImageDraw.Draw(img)
    # simple helmet: semi-circle on top
    draw.pieslice((48, -20, 208, 140), start=180, end=0, fill=(120,120,120,220))
    # rim
    draw.rectangle((48,80,208,96), fill=(80,80,80,255))
    img.save(path)

def create_sword(path, size):
    img = Image.new("RGBA", size, (0,0,0,0))
    draw = ImageDraw.Draw(img)
    # handle
    draw.rectangle((110,160,140,196), fill=(120,70,20,255))
    # guard
    draw.rectangle((96,150,154,160), fill=(180,180,180,255))
    # blade
    draw.polygon([(124,20),(132,150),(116,150)], fill=(200,200,200,255))
    img.save(path)

def create_shield(path, size):
    img = Image.new("RGBA", size, (0,0,0,0))
    draw = ImageDraw.Draw(img)
    # shield: rounded polygon
    draw.polygon([(56,64),(200,64),(176,168),(128,208),(80,168)], fill=(80,110,160,255))
    # border
    draw.line([(56,64),(200,64),(176,168),(128,208),(80,168),(56,64)], fill=(40,60,80,255), width=4)
    img.save(path)


if __name__ == "__main__":
    import os
    folder = os.path.dirname(__file__)
    for name,size in OUTPUTS.items():
        path = os.path.join(folder, name)
        if name == "duck_base.png":
            create_duck_base(path,size)
        elif name == "duck_helmet.png":
            create_helmet(path,size)
        elif name == "duck_sword.png":
            create_sword(path,size)
        elif name == "duck_shield.png":
            create_shield(path,size)
    print("Assets generated in", folder)
