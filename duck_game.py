from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from typing import List, Tuple

from PIL import Image, ImageOps

# Paths to local images (adjust filenames if yours differ)
BASE_DUCK_PATH = "assets/duck_base.png"
EQUIPMENT_PATHS = {
    "helmet": "assets/duck_helmet.png",
    "sword": "assets/duck_sword.png",
    "shield": "assets/duck_shield.png",
}


@dataclass
class Duck:
    name: str
    health: int = 20
    attack: int = 5
    defense: int = 2
    equipment: List[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.health > 0


def _open_image_or_placeholder(path: str, size: Tuple[int, int]) -> Image.Image:
    """Try to open an image from disk; if missing, return a transparent placeholder."""
    try:
        img = Image.open(path).convert("RGBA")
        # Optionally resize equipment to match canvas size proportionally
        img = ImageOps.contain(img, size)
        return img
    except Exception:
        # placeholder transparent image
        return Image.new("RGBA", size, (0, 0, 0, 0))


def generate_duck(equipment: List[str]) -> Image.Image:
    """
    Generate a duck image by compositing a base duck and overlaying equipment PNGs.

    Args:
        equipment: list of equipment keys (e.g. ['helmet','sword'])

    Returns:
        PIL.Image (RGBA)
    """
    # choose a canvas size; if base exists we'll use its size
    try:
        base = Image.open(BASE_DUCK_PATH).convert("RGBA")
    except Exception:
        # create a simple base duck placeholder (yellow circle on transparent)
        base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        circle = Image.new("RGBA", base.size, (0, 0, 0, 0))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(circle)
        bbox = (32, 48, 224, 208)
        draw.ellipse(bbox, fill=(255, 220, 0, 255))
        base = Image.alpha_composite(base, circle)

    canvas = base.copy()
    size = canvas.size

    # Overlay equipment images. Order matters: helmet on top, shield/sword may be below/side.
    # We'll apply in a deterministic order for visual consistency.
    order = ["shield", "sword", "helmet"]
    for key in order:
        if key in equipment:
            path = EQUIPMENT_PATHS.get(key)
            if path:
                equip_img = _open_image_or_placeholder(path, size)
                # paste with alpha mask to preserve transparency
                try:
                    canvas.alpha_composite(equip_img)
                except Exception:
                    canvas.paste(equip_img, (0, 0), equip_img)

    return canvas


def duck_to_bytes(image: Image.Image) -> io.BytesIO:
    """Convert a PIL Image to a BytesIO PNG stream suitable for sending as a file."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return buf


def resolve_turn(action1: str, action2: str, duck1: Duck, duck2: Duck) -> str:
    """
    Resolve a single turn between two ducks given their actions.

    Rules:
      - attack beats dodge
      - dodge beats defend
      - defend beats attack

    Damage calculation is simple: damage = max(1, attacker.attack - defender.defense)

    Returns a short textual summary of the turn (and mutates duck health).
    """
    beats = {
        "attack": "dodge",
        "dodge": "defend",
        "defend": "attack",
    }

    a1 = action1.lower()
    a2 = action2.lower()

    # tie
    if a1 == a2:
        return f"Ambos usan {a1}. Nada relevante ocurre."

    # action1 wins
    if beats.get(a1) == a2:
        dmg = max(1, duck1.attack - duck2.defense)
        duck2.health -= dmg
        return f"{duck1.name} usa {a1} y vence a {a2}. {duck2.name} pierde {dmg} de vida."

    # action2 wins
    if beats.get(a2) == a1:
        dmg = max(1, duck2.attack - duck1.defense)
        duck1.health -= dmg
        return f"{duck2.name} usa {a2} y vence a {a1}. {duck1.name} pierde {dmg} de vida."

    # fallback (shouldn't happen with valid actions)
    return "Acciones no resueltas correctamente."


def fight_ducks(duck1: Duck, duck2: Duck, rounds: int = 5) -> str:
    """
    Simulate a short fight between two ducks. Each turn both pick a random action.

    Returns a multi-line string summary of the fight and final winner.
    """
    actions = ["attack", "defend", "dodge"]
    log_lines = [f"Duelo: {duck1.name} vs {duck2.name}"]

    for r in range(1, rounds + 1):
        if not (duck1.is_alive() and duck2.is_alive()):
            break
        a1 = random.choice(actions)
        a2 = random.choice(actions)
        log_lines.append(f"Ronda {r}: {duck1.name} -> {a1} | {duck2.name} -> {a2}")
        res = resolve_turn(a1, a2, duck1, duck2)
        log_lines.append(res)
        log_lines.append(f"Estados: {duck1.name}({duck1.health}) - {duck2.name}({duck2.health})")

    # Determine winner
    if duck1.health > duck2.health:
        log_lines.append(f"Ganador: {duck1.name}!")
    elif duck2.health > duck1.health:
        log_lines.append(f"Ganador: {duck2.name}!")
    else:
        log_lines.append("Empate: ambos están igualados.")

    return "\n".join(log_lines)


def random_duck(name: str | None = None) -> Duck:
    """Helper to generate a random Duck instance with some equipment."""
    if not name:
        name = random.choice(["Pato A", "Pato B", "Sir Quacksalot", "Duke of Quack"]) 
    equip_keys = list(EQUIPMENT_PATHS.keys())
    eq = [k for k in equip_keys if random.random() < 0.5]
    return Duck(name=name, health=random.randint(15, 30), attack=random.randint(3, 8), defense=random.randint(1, 5), equipment=eq)
