#!/usr/bin/env python3
"""Local simulator for the Teddy War messages (no Discord / no DB required).

Run: python3 teddy_war_sim.py -n 6
"""
import os
import random
import time
import argparse

BASE_DIR = os.path.dirname(__file__)
TEDDY_ASSETS_DIR = os.path.join(BASE_DIR, "teddy wars")

def load_teddy_images():
    if not os.path.isdir(TEDDY_ASSETS_DIR):
        print("No teddy assets directory found:", TEDDY_ASSETS_DIR)
        return []
    files = [f for f in os.listdir(TEDDY_ASSETS_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    return [os.path.join(TEDDY_ASSETS_DIR, f) for f in files]

TEDDY_MESSAGE_GROUPS = {
    "pillow": {
        "attacks": [
            "{a} smacks {d} with a gigantic fluffy pillow — sweet dreams!",
            "{a} launches a surprise pillow bomb at {d}. Feathers everywhere!",
        ],
        "kills": [
            "{a} pillows {d} into a permanent nap. Zzzz...",
            "{d} was fluffed to oblivion by {a}. No waking up today.",
        ],
        "revives": [
            "{d} sneezes out a battery and bounces back!",
            "A stray pillow springs {d} back to life — recharge complete!",
        ],
        "taunts": [
            "{a} strikes a victory pose while feathers rain down on {d}.",
            "{a} ruffles {d}'s stuffing and laughs maniacally.",
        ],
    },
    "sword": {
        "attacks": [
            "{a} brandishes a foam sword and taps {d} — honorably incapacitated.",
            "{a} performs the legendary 'Cuddly Slash' and {d} topples.",
        ],
        "kills": [
            "{a} disarms {d} with a dramatic squeak — {d} falls dramatically.",
            "{d} is skewered by a glue-stick lance and exits stage left.",
        ],
        "revives": [
            "{d} patches up their plush seams and returns, fiercer than ever!",
            "{d} discovers a hidden button labeled 'Restart' and pops back in.",
        ],
        "taunts": [
            "{a} polishes their tiny sword and winks at {d}.",
            "{a} whispers 'I hug, therefore I win' to {d}.",
        ],
    },
    "epic": {
        "attacks": [
            "{a} leaps through a storm of fluff and lands a thunderous hug on {d}.",
            "{a} swings their glitter blade; {d} is stunned by the sparkle.",
        ],
        "kills": [
            "{d} is knocked into the pillow void — no return ticket.",
            "{a} delivers the 'Cuddle Overload' — system shutdown for {d}.",
        ],
        "revives": [
            "{d} miraculously regains fluff after applause from an invisible audience.",
            "A tiny fairy teddy tosses a stitch and {d} wakes up again.",
        ],
        "taunts": [
            "{a} does a slow clap with adorable paw gestures.",
            "{a} juggles feathers while {d} coughs fluff.",
        ],
    },
    "hero": {
        "attacks": [
            "{a} stares down {d} with heroic eyes and gives a noble poke.",
            "{a} charges bravely, wielding a sword twice their size.",
        ],
        "kills": [
            "{a} slays the shadow with a single squeak — legend born.",
            "{d} fades into bedtime stories after that heroic slap.",
        ],
        "revives": [
            "{d} finds hidden courage stuffed in their belly and stands up again.",
            "{d} drinks a cup of tiny tea and is back for round two.",
        ],
        "taunts": [
            "{a} taps their chest and says 'For the snuggles!'",
            "{a} strikes a heroic pose on a pile of pillows.",
        ],
    },
    "boss": {
        "attacks": [
            "{a} swings desperately at the looming plush shadow and hits its armor.",
            "{a} charges with reckless fluffiness; the ground trembles.",
        ],
        "kills": [
            "{a} barely survives; {d} is swallowed by the boss's scary fluff.",
            "{d} gets squashed under a giant paw and disappears.",
        ],
        "revives": [
            "{d} coughs up a spare pom-pom and returns to the fray!",
            "The crowd chants and {d} rematerializes, slightly singed but ready.",
        ],
        "taunts": [
            "{a} growls like a 2-inch warrior and it somehow works.",
            "{a} polishes their sword while the boss frowns.",
        ],
    },
}

TEDDY_IMAGE_GROUP_MAP = {}
for n in range(7768, 7785):
    name = f"IMG_{n}.jpg"
    if n in (7768, 7769):
        TEDDY_IMAGE_GROUP_MAP[name] = "pillow"
    elif n in (7781,):
        TEDDY_IMAGE_GROUP_MAP[name] = "hero"
    elif n in (7782, 7783, 7784):
        TEDDY_IMAGE_GROUP_MAP[name] = "boss"
    elif n in (7777, 7778, 7779, 7780):
        TEDDY_IMAGE_GROUP_MAP[name] = "epic"
    else:
        TEDDY_IMAGE_GROUP_MAP[name] = "sword"

def _get_teddy_messages_for_image(image_path: str):
    if not image_path:
        return None
    key = os.path.basename(image_path)
    group = TEDDY_IMAGE_GROUP_MAP.get(key)
    return TEDDY_MESSAGE_GROUPS.get(group)

def ensure_teddy_images(participants):
    assets = load_teddy_images()
    image_map = {}
    for uid in participants:
        chosen = random.choice(assets) if assets else None
        image_map[uid] = chosen
    return image_map


def _pick_non_repeating_image(candidate_paths, last_image: str | None = None):
    """Pick an image from candidates avoiding last_image when possible."""
    candidates = [p for p in candidate_paths if p and os.path.isfile(p)]
    for p in candidates:
        if p != last_image:
            return p
    assets = load_teddy_images()
    assets = [a for a in assets if a and a != last_image and os.path.isfile(a)]
    if assets:
        return random.choice(assets)
    return candidates[0] if candidates else None

def simulate(num_players: int = 4, pause: float = 0.4):
    sample_names = ["Alice", "Bob", "Charlie", "Dana", "Eve", "Frank", "Gina", "Hank"]
    players = [
        {"id": 1000 + i, "name": sample_names[i % len(sample_names)]}
        for i in range(num_players)
    ]
    alive = [p["id"] for p in players]
    id_to_name = {p["id"]: p["name"] for p in players}
    image_map = ensure_teddy_images(alive)
    last_posted_image = None

    print("Starting Teddy War — participants:")
    for p in players:
        print(f" - @{p['name']} (id={p['id']}) -> image={os.path.basename(image_map[p['id']]) if image_map[p['id']] else 'None'}")
    print("\n--- Battle log ---\n")

    while len(alive) > 1:
        a, d = random.sample(alive, 2)
        attacker_img = image_map.get(a)
        defender_img = image_map.get(d)
        msgs = _get_teddy_messages_for_image(attacker_img) or TEDDY_MESSAGE_GROUPS["sword"]
        attack_msg = random.choice(msgs["attacks"]).format(a=f"@{id_to_name[a]}", d=f"@{id_to_name[d]}")
        post_img = _pick_non_repeating_image([attacker_img, defender_img], last_posted_image)
        print("ATTACK:", attack_msg)
        print("IMAGE:", os.path.basename(post_img) if post_img else "(no image)")
        last_posted_image = post_img
        time.sleep(pause)

        killer, victim = (a, d) if random.random() < 0.6 else (d, a)
        if victim in alive:
            alive.remove(victim)
        kill_msgs = _get_teddy_messages_for_image(image_map.get(killer)) or TEDDY_MESSAGE_GROUPS["sword"]
        kill_text = random.choice(kill_msgs["kills"]).format(a=f"@{id_to_name[killer]}", d=f"@{id_to_name[victim]}")
        post_img = _pick_non_repeating_image([image_map.get(killer), image_map.get(victim)], last_posted_image)
        print("KILL:", kill_text)
        print("IMAGE:", os.path.basename(post_img) if post_img else "(no image)")
        last_posted_image = post_img
        time.sleep(pause)

        # revive chance
        if random.random() < 0.5 and victim not in alive:
            alive.append(victim)
            rev_msgs = _get_teddy_messages_for_image(image_map.get(victim)) or TEDDY_MESSAGE_GROUPS["sword"]
            rev_msg = random.choice(rev_msgs["revives"]).format(d=f"@{id_to_name[victim]}")
            post_img = _pick_non_repeating_image([image_map.get(victim)], last_posted_image)
            print("REVIVE:", rev_msg)
            print("IMAGE:", os.path.basename(post_img) if post_img else "(no image)")
            last_posted_image = post_img
            time.sleep(pause)

        print("---")

    winner = alive[0]
    print(f"\nTournament finished! Winner: @{id_to_name[winner]} (id={winner})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--num", type=int, default=4, help="Number of participants (2-8)")
    parser.add_argument("-s", "--speed", type=float, default=0.4, help="Pause between events (seconds)")
    args = parser.parse_args()
    simulate(num_players=max(2, min(8, args.num)), pause=max(0.05, args.speed))


if __name__ == "__main__":
    main()
