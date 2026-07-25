#!/usr/bin/env python3
"""Team Teddy War - Battle royale with teams of 2 teddy bears!"""
import os
import random

BASE_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
TEDDY_TEAM_ASSETS_DIR = os.path.join(REPO_ROOT, "teddy_wars2")

def load_team_teddy_images():
    """Load teddy images from teddy_wars2 directory."""
    if not os.path.isdir(TEDDY_TEAM_ASSETS_DIR):
        print("No teddy team assets directory found:", TEDDY_TEAM_ASSETS_DIR)
        return []
    files = [f for f in os.listdir(TEDDY_TEAM_ASSETS_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and "victory" not in f.lower()]
    return [os.path.join(TEDDY_TEAM_ASSETS_DIR, f) for f in files]


def get_victory_image():
    """Get the victory.png image for team winners."""
    victory_path = os.path.join(TEDDY_TEAM_ASSETS_DIR, "victory.png")
    if os.path.exists(victory_path):
        return victory_path
    return None


# Textos divertidos y graciosos para batallas por equipos
# Formato: {team_a} es el equipo atacante, {team_d} es el equipo defensor
# {member_a1}, {member_a2} son los miembros del equipo atacante
# {member_d1}, {member_d2} son los miembros del equipo defensor
TEAM_BATTLE_TEXTS = {
    "en": {
        "attacks": [
            "💥 Team {team_a} ({member_a1} & {member_a2}) launch a synchronized pillow attack on Team {team_d}!",
            "🧸 {member_a1} and {member_a2} form a cuddle cannon and blast Team {team_d} with fluff!",
            "⚔️ Team {team_a} executes the legendary 'Double Hug Slam' on {member_d1} and {member_d2}!",
            "🌪️ {member_a1} distracts while {member_a2} sneaks behind — Team {team_d} gets ambushed!",
            "💫 The dynamic duo of Team {team_a} combines their plush powers against Team {team_d}!",
            "🎯 {member_a1} throws {member_a2} like a furry missile at Team {team_d}!",
            "🔥 Team {team_a} activates 'Friendship Ultra Combo' — Team {team_d} is stunned!",
            "🌟 {member_a1} and {member_a2} do a synchronized victory dance while attacking Team {team_d}!",
            "💪 Double trouble! Team {team_a} gangs up on poor Team {team_d} with stuffing fury!",
            "🎪 {member_a1} juggles pillows while {member_a2} tickles Team {team_d} into submission!",
        ],
        "eliminations": [
            "💀 Team {team_d} has been eliminated! {member_d1} and {member_d2} are now snoring forever...",
            "😴 Team {team_a} sends Team {team_d} to the eternal nap zone! Zzzzz...",
            "🏴 {member_d1} and {member_d2} have been fluffed to oblivion by the mighty Team {team_a}!",
            "⚰️ Team {team_d} is out! They fought valiantly but got hugged too hard!",
            "👻 RIP Team {team_d} — defeated by the unstoppable cuddle power of Team {team_a}!",
            "💫 Team {team_d} poofs into a cloud of cotton! Team {team_a} wins this round!",
            "🌙 Good night, Team {team_d}! {member_d1} and {member_d2} are off to dreamland!",
            "🎭 The curtain falls on Team {team_d} — dramatic exit courtesy of Team {team_a}!",
            "🔚 Team {team_d} has been cuddled into retirement! Game over for {member_d1} & {member_d2}!",
            "💤 Team {team_a} tucks Team {team_d} into bed... permanently! Sweet dreams!",
        ],
        "victory": [
            "🏆 VICTORY! Team {team_winner} ({member_1} & {member_2}) are the last teddies standing!",
            "👑 All hail Team {team_winner}! {member_1} and {member_2} have conquered the cuddle battlefield!",
            "🎉 CHAMPIONS! Team {team_winner} proves that friendship and fluff conquer all!",
            "⭐ Team {team_winner} wins! {member_1} and {member_2} are the ultimate plush warriors!",
            "🥇 The battle is over! Team {team_winner} stands victorious atop a mountain of pillows!",
            "💪 Legendary! Team {team_winner} ({member_1} & {member_2}) have achieved teddy immortality!",
            "🌟 UNDEFEATED! Team {team_winner} reigns supreme in this fuzzy apocalypse!",
            "🎊 {member_1} and {member_2} of Team {team_winner} are crowned the Cuddle Champions!",
            "🔥 FLAWLESS VICTORY! Team {team_winner} dominates with their unstoppable teamwork!",
            "✨ Team {team_winner} wins! The stadium erupts in stuffing and confetti!",
        ],
        "taunts": [
            "😎 Team {team_a} strikes a victory pose! Team {team_d} can only watch in awe!",
            "🤪 {member_a1} and {member_a2} do the floss dance over Team {team_d}'s fallen bodies!",
            "😏 Team {team_a} polishes their tiny weapons while Team {team_d} sweats nervously!",
            "🎵 {member_a1} sings a victory song while {member_a2} plays air guitar! Team {team_d} is not amused!",
            "🌈 Team {team_a} leaves a trail of glitter and giggles — Team {team_d} is demoralized!",
            "💅 {member_a1} examines their claws while {member_a2} whispers 'you're next' to Team {team_d}!",
            "🎭 Team {team_a} reenacts their victory in slow motion! Team {team_d} cringes!",
            "🍿 {member_a1} and {member_a2} grab popcorn and watch Team {team_d} struggle!",
        ],
    },
    "es": {
        "attacks": [
            "💥 ¡El Equipo {team_a} ({member_a1} y {member_a2}) lanza un ataque sincronizado de almohadas contra el Equipo {team_d}!",
            "🧸 ¡{member_a1} y {member_a2} forman un cañón de abrazos y bombardean al Equipo {team_d} con pelusa!",
            "⚔️ ¡El Equipo {team_a} ejecuta el legendario 'Abrazo Doble Mortal' contra {member_d1} y {member_d2}!",
            "🌪️ ¡{member_a1} distrae mientras {member_a2} se cuela por detrás — el Equipo {team_d} cae en la emboscada!",
            "💫 ¡El dúo dinámico del Equipo {team_a} combina sus poderes de peluche contra el Equipo {team_d}!",
            "🎯 ¡{member_a1} lanza a {member_a2} como un misil peludo contra el Equipo {team_d}!",
            "🔥 ¡El Equipo {team_a} activa 'Combo Ultra de Amistad' — el Equipo {team_d} está aturdido!",
            "🌟 ¡{member_a1} y {member_a2} hacen un baile de victoria sincronizado mientras atacan al Equipo {team_d}!",
            "💪 ¡Doble problema! ¡El Equipo {team_a} se une contra el pobre Equipo {team_d} con furia de relleno!",
            "🎪 ¡{member_a1} hace malabares con almohadas mientras {member_a2} hace cosquillas al Equipo {team_d} hasta la rendición!",
        ],
        "eliminations": [
            "💀 ¡El Equipo {team_d} ha sido eliminado! {member_d1} y {member_d2} ahora roncan eternamente...",
            "😴 ¡El Equipo {team_a} envía al Equipo {team_d} a la zona de siesta eterna! Zzzzz...",
            "🏴 ¡{member_d1} y {member_d2} han sido acolchados al olvido por el poderoso Equipo {team_a}!",
            "⚰️ ¡El Equipo {team_d} está fuera! ¡Lucharon valientemente pero los abrazaron demasiado fuerte!",
            "👻 DEP Equipo {team_d} — ¡derrotados por el imparable poder de abrazo del Equipo {team_a}!",
            "💫 ¡El Equipo {team_d} se convierte en una nube de algodón! ¡El Equipo {team_a} gana esta ronda!",
            "🌙 ¡Buenas noches, Equipo {team_d}! ¡{member_d1} y {member_d2} se van al país de los sueños!",
            "🎭 ¡Cae el telón sobre el Equipo {team_d} — salida dramática cortesía del Equipo {team_a}!",
            "🔚 ¡El Equipo {team_d} ha sido acurrucado hasta la jubilación! ¡Fin del juego para {member_d1} y {member_d2}!",
            "💤 ¡El Equipo {team_a} arropa al Equipo {team_d}... ¡permanentemente! ¡Dulces sueños!",
        ],
        "victory": [
            "🏆 ¡VICTORIA! ¡El Equipo {team_winner} ({member_1} y {member_2}) son los últimos ositos en pie!",
            "👑 ¡Gloria al Equipo {team_winner}! ¡{member_1} y {member_2} han conquistado el campo de batalla de abrazos!",
            "🎉 ¡CAMPEONES! ¡El Equipo {team_winner} demuestra que la amistad y la pelusa lo conquistan todo!",
            "⭐ ¡El Equipo {team_winner} gana! ¡{member_1} y {member_2} son los guerreros de peluche definitivos!",
            "🥇 ¡La batalla ha terminado! ¡El Equipo {team_winner} se alza victorioso sobre una montaña de almohadas!",
            "💪 ¡Legendario! ¡El Equipo {team_winner} ({member_1} y {member_2}) han logrado la inmortalidad de osito!",
            "🌟 ¡INVICTOS! ¡El Equipo {team_winner} reina supremo en este apocalipsis peludo!",
            "🎊 ¡{member_1} y {member_2} del Equipo {team_winner} son coronados los Campeones de Abrazos!",
            "🔥 ¡VICTORIA IMPECABLE! ¡El Equipo {team_winner} domina con su trabajo en equipo imparable!",
            "✨ ¡El Equipo {team_winner} gana! ¡El estadio explota en relleno y confeti!",
        ],
        "taunts": [
            "😎 ¡El Equipo {team_a} hace una pose de victoria! ¡El Equipo {team_d} solo puede mirar con asombro!",
            "🤪 ¡{member_a1} y {member_a2} bailan sobre los cuerpos caídos del Equipo {team_d}!",
            "😏 ¡El Equipo {team_a} pule sus armas diminutas mientras el Equipo {team_d} suda nerviosamente!",
            "🎵 ¡{member_a1} canta una canción de victoria mientras {member_a2} toca la guitarra invisible! ¡El Equipo {team_d} no se divierte!",
            "🌈 ¡El Equipo {team_a} deja un rastro de purpurina y risitas — el Equipo {team_d} está desmoralizado!",
            "💅 ¡{member_a1} examina sus garras mientras {member_a2} susurra 'ustedes siguen' al Equipo {team_d}!",
            "🎭 ¡El Equipo {team_a} recrea su victoria en cámara lenta! ¡El Equipo {team_d} se estremece!",
            "🍿 ¡{member_a1} y {member_a2} agarran palomitas y ven al Equipo {team_d} luchar!",
        ],
    },
}


def get_team_text(lang: str, category: str) -> list[str]:
    """Get random battle text in the specified language."""
    lang = lang if lang in ("en", "es") else "en"
    return TEAM_BATTLE_TEXTS.get(lang, TEAM_BATTLE_TEXTS["en"]).get(category, [])


def ensure_team_teddy_images(teams: dict[int, list[int]]) -> dict[int, str]:
    """Assign a random teddy image to each player from teddy_wars2."""
    assets = load_team_teddy_images()
    if not assets:
        return {}
    
    image_map = {}
    all_players = []
    for team_members in teams.values():
        all_players.extend(team_members)
    
    for player_id in all_players:
        image_map[player_id] = random.choice(assets)
    
    return image_map


def pick_random_team_image(team_members: list[int], image_map: dict[int, str], last_image: str | None = None) -> str | None:
    """Pick a random image from team members, avoiding the last posted image if possible."""
    candidates = [image_map.get(m) for m in team_members if m in image_map]
    candidates = [c for c in candidates if c and os.path.isfile(c)]
    
    # Try to avoid repeating the last image
    different = [c for c in candidates if c != last_image]
    if different:
        return random.choice(different)
    
    # If all are the same as last_image or no candidates, just pick any
    if candidates:
        return random.choice(candidates)
    
    # Fallback to any asset
    assets = load_team_teddy_images()
    if assets:
        return random.choice(assets)
    
    return None
