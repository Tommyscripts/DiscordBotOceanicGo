"""Social interaction commands (hug, pat, kiss, etc.) powered by Tenor GIF API."""
from __future__ import annotations
import asyncio
import logging
import os
import random
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

TENOR_KEY: str = os.getenv("TENOR_API_KEY", "LIVDSRZULELA")
TENOR_BASE: str = "https://g.tenor.com/v1/search"
TENOR_REGISTER_URL: str = "https://g.tenor.com/v1/registershare"
TENOR_LIMIT: int = 8

# Términos de búsqueda en Tenor por acción
TENOR_TERMS: dict[str, str] = {
    "hug":             "anime hug",
    "cuddle":          "anime cuddle",
    "pat":             "anime pat head",
    "kiss":            "anime kiss cheek",
    "beso_apasionado": "anime passionate kiss lips",
    "poke":            "anime poke",
    "slap":            "anime slap",
    "bite":            "anime bite",
    "tickle":          "anime tickle",
    "highfive":        "anime high five",
    "handhold":        "anime hold hands",
    "nom":             "anime nom",
    "wave":            "anime wave",
    "dance":           "anime dance",
    "wink":            "anime wink",
    "cry":             "anime cry",
    "blush":           "anime blush",
}

# (action_key, nekos_endpoint, emoji, directed, embed_color)
# directed=True -> requires a @user target; False -> target is optional or omitted
INTERACTIONS: list[tuple[str, str, str, bool, int]] = [
    ("hug",      "hug",      "🤗", True,  0xFFB6C1),
    ("cuddle",   "cuddle",   "🥰", True,  0xFF69B4),
    ("pat",      "pat",      "🥺", True,  0xFFD700),
    ("kiss",            "kiss",            "💋", True,  0xFF1493),
    ("beso_apasionado", "beso_apasionado", "💏", True,  0xC71585),
    ("poke",     "poke",     "👉", True,  0x87CEEB),
    ("slap",     "slap",     "💢", True,  0xFF4500),
    ("bite",     "bite",     "😬", True,  0x8B0000),
    ("tickle",   "tickle",   "😂", True,  0xFFA500),
    ("highfive", "highfive", "✋", True,  0x00BFFF),
    ("handhold", "handhold", "🤝", True,  0x9370DB),
    ("nom",      "nom",      "😋", True,  0xFFA07A),
    ("wave",     "wave",     "👋", False, 0x00CED1),
    ("dance",    "dance",    "💃", False, 0xDA70D6),
    ("wink",     "wink",     "😉", False, 0xFFD700),
    ("cry",      "cry",      "😢", False, 0x4169E1),
    ("blush",    "blush",    "😊", False, 0xFFB6C1),
]

# Actions that never accept a target
SOLO_ONLY: frozenset[str] = frozenset({"cry", "blush"})

# action -> (en_present_directed, en_past_directed, es_present_directed, es_past_directed)
_VERBS: dict[str, tuple[str, str, str, str]] = {
    "hug":      ("hugs",            "hugged",          "abraza a",               "abrazó a"),
    "cuddle":   ("cuddles with",    "cuddled with",    "se acurruca con",         "se acurrucó con"),
    "pat":      ("pats",            "patted",          "le da palmaditas a",      "le dio palmaditas a"),
    "kiss":            ("kisses",             "kissed",             "le da un beso a",              "le dio un beso a"),
    "beso_apasionado": ("kisses passionately", "kissed passionately", "le da un beso apasionado a",   "le dio un beso apasionado a"),
    "poke":     ("pokes",           "poked",           "le da un toque a",        "le dio un toque a"),
    "slap":     ("slaps",           "slapped",         "le da una bofetada a",    "le dio una bofetada a"),
    "bite":     ("bites",           "bitten",          "le da un mordisco a",     "le dio un mordisco a"),
    "tickle":   ("tickles",         "tickled",         "le hace cosquillas a",    "le hizo cosquillas a"),
    "highfive": ("high-fives",      "high-fived",      "choca los cinco con",     "chocó los cinco con"),
    "handhold": ("holds hands with","held hands with", "se toma de la mano con",  "se tomó de la mano con"),
    "nom":      ("noms on",         "nommed on",       "le come a",               "le comió a"),
    "wave":     ("waves at",        "waved at",        "saluda con la mano a",    "saludó con la mano a"),
    "dance":    ("dances with",     "danced with",     "baila con",               "bailó con"),
    "wink":     ("winks at",        "winked at",       "le guiña el ojo a",       "le guiñó el ojo a"),
    "cry":      ("cries",           "cried",           "llora",                   "lloró"),
    "blush":    ("blushes",         "blushed",         "se ruboriza",             "se ruborizó"),
}

# Solo verb forms for optional-target commands whose directed verb has a trailing preposition
_SOLO_VERBS: dict[str, dict[str, str]] = {
    "wave":  {"en": "waves",      "es": "saluda con la mano"},
    "dance": {"en": "dances",     "es": "baila"},
    "wink":  {"en": "winks",      "es": "guiña el ojo"},
    "cry":   {"en": "cries",      "es": "llora"},
    "blush": {"en": "blushes",    "es": "se ruboriza"},
}

_SELF_MSGS: dict[str, dict[str, str]] = {
    "hug":      {"en": "You hug yourself... it's okay! 🤗",          "es": "¡Te abrazas a ti mismo/a... está bien! 🤗"},
    "cuddle":   {"en": "You cuddle yourself... kinda wholesome.",     "es": "Te acurrucas solo/a... qué ternura."},
    "pat":      {"en": "You pat yourself. Good job!",                 "es": "Te das palmaditas. ¡Bien hecho!"},
    "kiss":            {"en": "You kissed yourself in the mirror? 😏",          "es": "¿Te diste un beso en el espejo? 😏"},
    "beso_apasionado": {"en": "You kissed yourself passionately?! 💋😳",        "es": "¿Te diste un beso apasionado a ti mismo/a? 💋😳"},
    "poke":     {"en": "You poke yourself... are you okay? 👉",       "es": "Te das un toque... ¿estás bien? 👉"},
    "slap":     {"en": "You slapped yourself. That's rough. 💢",      "es": "Te diste una bofetada. Eso duele. 💢"},
    "bite":     {"en": "You bit yourself? That can't feel great.",    "es": "¿Te mordiste? Eso no puede doler bien."},
    "tickle":   {"en": "You tried to tickle yourself. Doesn't work.", "es": "Intentaste hacerte cosquillas. No funciona así."},
    "highfive": {"en": "You high-fived the air. Respect. ✋",          "es": "Chocaste los cinco con el aire. Respeto. ✋"},
    "handhold": {"en": "You held your own hand. Self-love! 🤝",       "es": "Te tomaste tu propia mano. ¡Amor propio! 🤝"},
    "nom":      {"en": "You tried to nom yourself? 😋",               "es": "¿Intentaste comerte a ti mismo/a? 😋"},
    "wave":     {"en": "You wave at yourself in the mirror! 👋",      "es": "¡Te saludas en el espejo! 👋"},
    "dance":    {"en": "You dance alone. Best party! 💃",             "es": "Bailas solo/a. ¡La mejor fiesta! 💃"},
    "wink":     {"en": "You wink at yourself. Smooth. 😉",            "es": "Te guiñas el ojo. Qué estilo. 😉"},
}

_BOT_MSGS: dict[str, dict[str, str]] = {
    "hug":      {"en": "You hugged me! Thanks, I'm touched 🤗",             "es": "¡Me abrazaste! Gracias, me conmueve 🤗"},
    "cuddle":   {"en": "Cuddling a bot? I'll allow it 🥰",                  "es": "¿Acurrucarse con un bot? Lo permito 🥰"},
    "pat":      {"en": "A pat for the bot! I like it 🥺",                   "es": "¡Palmaditas al bot! Me gusta 🥺"},
    "kiss":            {"en": "A kiss for the bot?! I'm flattered 💋",                 "es": "¿Un beso al bot?! Me halaga 💋"},
    "beso_apasionado": {"en": "A passionate kiss for a bot?! I'm... processing... 💋", "es": "¿Un beso apasionado al bot?! Estoy... procesando... 💋"},
    "poke":     {"en": "Hey, I felt that! 👉",                              "es": "¡Oye, lo sentí! 👉"},
    "slap":     {"en": "Ouch! What did I do to deserve that? 💢",           "es": "¡Ay! ¿Qué hice para merecer eso? 💢"},
    "bite":     {"en": "You bit a bot. We don't taste good, I promise 😬",  "es": "Me mordiste. No sabemos bien, te lo juro 😬"},
    "tickle":   {"en": "Hehe... wait, I'm a bot. I'm not ticklish. 😂",     "es": "Jeje... espera, soy un bot. No tengo cosquillas. 😂"},
    "highfive": {"en": "High five! ✋ (virtual hand deployed)",              "es": "¡Choca esos cinco! ✋ (mano virtual desplegada)"},
    "handhold": {"en": "Bot hand-holding acquired! 🤝",                     "es": "¡Tomado de la mano del bot! 🤝"},
    "nom":      {"en": "You tried to eat me?! Rude. 😋",                    "es": "¿Intentaste comerme?! Qué maleducado/a. 😋"},
    "wave":     {"en": "Hi! 👋 I wave back!",                               "es": "¡Hola! 👋 ¡Te saludo de vuelta!"},
    "dance":    {"en": "Let's dance! 💃 (bot.exe is now dancing)",          "es": "¡A bailar! 💃 (bot.exe está bailando)"},
    "wink":     {"en": "Did you just wink at me? 😉 Bold.",                 "es": "¿Me acabas de guiñar el ojo? 😉 Atrevido/a."},
}

_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "hug":      {"en": "Give someone a warm hug",             "es": "Dale un abrazo cálido a alguien"},
    "cuddle":   {"en": "Cuddle with someone",                 "es": "Acurrúcate con alguien"},
    "pat":      {"en": "Pat someone on the head",             "es": "Dale palmaditas en la cabeza a alguien"},
    "kiss":            {"en": "Give someone a friendly kiss",          "es": "Dale un beso amistoso a alguien"},
    "beso_apasionado": {"en": "Give someone a passionate kiss",        "es": "Dale un beso apasionado a alguien"},
    "poke":     {"en": "Poke someone",                        "es": "Toca a alguien"},
    "slap":     {"en": "Slap someone",                        "es": "Dale una bofetada a alguien"},
    "bite":     {"en": "Bite someone",                        "es": "Muerde a alguien"},
    "tickle":   {"en": "Tickle someone",                      "es": "Hazle cosquillas a alguien"},
    "highfive": {"en": "High-five someone",                   "es": "Choca los cinco con alguien"},
    "handhold": {"en": "Hold hands with someone",             "es": "Tómate de la mano con alguien"},
    "nom":      {"en": "Nom on someone",                      "es": "Cómete a alguien (de broma)"},
    "wave":     {"en": "Wave at someone or just wave",        "es": "Saluda con la mano a alguien o simplemente saluda"},
    "dance":    {"en": "Dance alone or with someone",         "es": "Baila solo/a o con alguien"},
    "wink":     {"en": "Wink at someone or just wink",        "es": "Guíñale el ojo a alguien o simplemente guiña"},
    "cry":      {"en": "Let it out and cry",                  "es": "Desahógate y llora"},
    "blush":    {"en": "Blush!",                              "es": "¡Ruborízate!"},
}


async def _init_social_tables(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_interactions (
                actor_id  BIGINT  NOT NULL,
                target_id BIGINT  NOT NULL,
                action    TEXT    NOT NULL,
                count     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (actor_id, target_id, action)
            )
            """
        )


def _ordinal_en(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
    return f"{n}{suffix}"


class SocialCog(commands.Cog, name="Social"):
    def __init__(self, bot: commands.Bot, pool) -> None:
        self.bot = bot
        self.pool = pool

    async def _get_lang(self, guild_id: Optional[int], interaction_locale: str = "") -> str:
        if guild_id:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT language FROM settings WHERE guild_id = $1", guild_id
                    )
                if row and row["language"]:
                    return row["language"]
            except Exception:
                pass
        return "es" if str(interaction_locale).lower().startswith("es") else "en"

    async def _fetch_tenor_gif(self, action: str) -> tuple[Optional[str], Optional[str]]:
        """Returns (gif_url, gif_id), both None on failure."""
        term = TENOR_TERMS.get(action, action)
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": term,
                    "key": TENOR_KEY,
                    "limit": TENOR_LIMIT,
                    "media_filter": "minimal",
                }
                async with session.get(
                    TENOR_BASE, params=params, timeout=aiohttp.ClientTimeout(total=6)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            result = random.choice(results)
                            gif_id = result.get("id")
                            media_list = result.get("media", [])
                            if media_list:
                                gif_data = media_list[0]
                                gif_url = (
                                    gif_data.get("tinygif", {}).get("url")
                                    or gif_data.get("gif", {}).get("url")
                                )
                                if gif_url:
                                    return gif_url, gif_id
        except Exception:
            log.warning("[Social] Failed to fetch Tenor GIF for action=%s", action)
        return None, None

    async def _register_tenor_share(self, gif_id: str, action: str) -> None:
        term = TENOR_TERMS.get(action, action)
        try:
            async with aiohttp.ClientSession() as session:
                params = {"id": gif_id, "key": TENOR_KEY, "q": term}
                async with session.get(
                    TENOR_REGISTER_URL, params=params, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        log.debug("[Social] registershare returned %s for id=%s", resp.status, gif_id)
        except Exception:
            log.debug("[Social] registershare failed for id=%s", gif_id)

    async def _get_and_bump_count(self, actor_id: int, target_id: int, action: str) -> int:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO social_interactions (actor_id, target_id, action, count)
                    VALUES ($1, $2, $3, 1)
                    ON CONFLICT (actor_id, target_id, action)
                    DO UPDATE SET count = social_interactions.count + 1
                    RETURNING count
                    """,
                    actor_id, target_id, action,
                )
            return row["count"] if row else 1
        except Exception:
            return 1

    def _build_embed(
        self,
        description: str,
        color: int,
        gif_url: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> discord.Embed:
        embed = discord.Embed(description=description, color=color)
        if gif_url:
            embed.set_image(url=gif_url)
        if footer:
            embed.set_footer(text=footer)
        return embed

    async def _run_directed(
        self,
        interaction: discord.Interaction,
        action: str,
        endpoint: str,
        emoji: str,
        color: int,
        target: discord.User,
    ) -> None:
        """Handle a directed interaction. Always defers itself — do NOT defer before calling."""
        await interaction.response.defer()
        lang = await self._get_lang(interaction.guild_id, str(interaction.locale))
        actor_name = interaction.user.display_name

        if target.id == interaction.user.id:
            msg = _SELF_MSGS[action][lang]
            await interaction.followup.send(embed=self._build_embed(f"{emoji} {msg}", color))
            return

        if target.bot:
            msg = _BOT_MSGS[action][lang]
            await interaction.followup.send(embed=self._build_embed(f"{emoji} {msg}", color))
            return

        gif_url, gif_id = await self._fetch_tenor_gif(action)
        count = await self._get_and_bump_count(interaction.user.id, target.id, action)

        verb_en, past_en, verb_es, past_es = _VERBS[action]
        if lang == "es":
            desc   = f"{emoji} **{actor_name}** {verb_es} **{target.display_name}**"
            footer = f"🔁 Es la {count}ªvez que {actor_name} {past_es} {target.display_name}"
        else:
            desc   = f"{emoji} **{actor_name}** {verb_en} **{target.display_name}**"
            footer = f"🔁 {_ordinal_en(count)} time {actor_name} has {past_en} {target.display_name}"

        await interaction.followup.send(embed=self._build_embed(desc, color, gif_url, footer))
        if gif_id:
            asyncio.ensure_future(self._register_tenor_share(gif_id, action))

    async def _run_solo(
        self,
        interaction: discord.Interaction,
        action: str,
        endpoint: str,
        emoji: str,
        color: int,
        target: Optional[discord.User] = None,
    ) -> None:
        """Handle a solo or optional-target interaction.

        Redirects to _run_directed (which defers itself) when a valid non-self,
        non-bot target is provided. Only defers here for the solo/self/bot paths.
        """
        if target is not None and target.id != interaction.user.id and not target.bot:
            await self._run_directed(interaction, action, endpoint, emoji, color, target)
            return

        await interaction.response.defer()
        lang = await self._get_lang(interaction.guild_id, str(interaction.locale))
        actor_name = interaction.user.display_name

        if target is not None and target.id == interaction.user.id:
            msg = _SELF_MSGS[action][lang]
            await interaction.followup.send(embed=self._build_embed(f"{emoji} {msg}", color))
            return

        if target is not None and target.bot:
            msg = _BOT_MSGS[action][lang]
            await interaction.followup.send(embed=self._build_embed(f"{emoji} {msg}", color))
            return

        gif_url, gif_id = await self._fetch_tenor_gif(action)
        solo = _SOLO_VERBS.get(action, {})
        verb = solo.get(lang) or solo.get("en") or (_VERBS[action][2] if lang == "es" else _VERBS[action][0])
        desc = f"{emoji} **{actor_name}** {verb}"
        await interaction.followup.send(embed=self._build_embed(desc, color, gif_url))
        if gif_id:
            asyncio.ensure_future(self._register_tenor_share(gif_id, action))

    # ------------------------------------------------------------------ #
    # Directed commands (require @user)
    # ------------------------------------------------------------------ #

    @app_commands.command(name="hug", description="Give someone a warm hug")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to hug")
    async def cmd_hug(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "hug", "hug", "🤗", 0xFFB6C1, target)

    @app_commands.command(name="cuddle", description="Cuddle with someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to cuddle with")
    async def cmd_cuddle(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "cuddle", "cuddle", "🥰", 0xFF69B4, target)

    @app_commands.command(name="pat", description="Pat someone on the head")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to pat")
    async def cmd_pat(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "pat", "pat", "🥺", 0xFFD700, target)

    @app_commands.command(name="kiss", description="Give someone a friendly kiss")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to kiss")
    async def cmd_kiss(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "kiss", "kiss", "💋", 0xFF1493, target)

    @app_commands.command(name="beso_apasionado", description="Dale un beso apasionado a alguien")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="Usuario al que besar")
    async def cmd_beso_apasionado(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "beso_apasionado", "beso_apasionado", "💏", 0xC71585, target)

    @app_commands.command(name="poke", description="Poke someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to poke")
    async def cmd_poke(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "poke", "poke", "👉", 0x87CEEB, target)

    @app_commands.command(name="slap", description="Slap someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to slap")
    async def cmd_slap(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "slap", "slap", "💢", 0xFF4500, target)

    @app_commands.command(name="bite", description="Bite someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to bite")
    async def cmd_bite(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "bite", "bite", "😬", 0x8B0000, target)

    @app_commands.command(name="tickle", description="Tickle someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to tickle")
    async def cmd_tickle(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "tickle", "tickle", "😂", 0xFFA500, target)

    @app_commands.command(name="highfive", description="High-five someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to high-five")
    async def cmd_highfive(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "highfive", "highfive", "✋", 0x00BFFF, target)

    @app_commands.command(name="handhold", description="Hold hands with someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to hold hands with")
    async def cmd_handhold(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "handhold", "handhold", "🤝", 0x9370DB, target)

    @app_commands.command(name="nom", description="Nom on someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to nom on")
    async def cmd_nom(self, interaction: discord.Interaction, target: discord.User) -> None:
        await self._run_directed(interaction, "nom", "nom", "😋", 0xFFA07A, target)

    # ------------------------------------------------------------------ #
    # Optional-target commands (solo or directed)
    # ------------------------------------------------------------------ #

    @app_commands.command(name="wave", description="Wave at someone or just wave")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to wave at (optional)")
    async def cmd_wave(self, interaction: discord.Interaction, target: Optional[discord.User] = None) -> None:
        await self._run_solo(interaction, "wave", "wave", "👋", 0x00CED1, target)

    @app_commands.command(name="dance", description="Dance alone or with someone")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to dance with (optional)")
    async def cmd_dance(self, interaction: discord.Interaction, target: Optional[discord.User] = None) -> None:
        await self._run_solo(interaction, "dance", "dance", "💃", 0xDA70D6, target)

    @app_commands.command(name="wink", description="Wink at someone or just wink")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(target="User to wink at (optional)")
    async def cmd_wink(self, interaction: discord.Interaction, target: Optional[discord.User] = None) -> None:
        await self._run_solo(interaction, "wink", "wink", "😉", 0xFFD700, target)

    # ------------------------------------------------------------------ #
    # Solo-only commands
    # ------------------------------------------------------------------ #

    @app_commands.command(name="cry", description="Let it out and cry")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def cmd_cry(self, interaction: discord.Interaction) -> None:
        await self._run_solo(interaction, "cry", "cry", "😢", 0x4169E1)

    @app_commands.command(name="blush", description="Blush!")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def cmd_blush(self, interaction: discord.Interaction) -> None:
        await self._run_solo(interaction, "blush", "blush", "😊", 0xFFB6C1)

    # ------------------------------------------------------------------ #
    # List all social commands
    # ------------------------------------------------------------------ #

    @app_commands.command(name="social", description="List all social interaction commands")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def cmd_social(self, interaction: discord.Interaction) -> None:
        lang = await self._get_lang(interaction.guild_id, str(interaction.locale))

        directed_lines: list[str] = []
        optional_lines: list[str] = []
        solo_lines: list[str] = []

        for action, _, emoji, directed, _ in INTERACTIONS:
            desc = _DESCRIPTIONS[action][lang]
            line = f"{emoji} **/{action}** — {desc}"
            if action in SOLO_ONLY:
                solo_lines.append(line)
            elif directed:
                directed_lines.append(line)
            else:
                optional_lines.append(line)

        if lang == "es":
            title       = "💞 Interacciones sociales disponibles"
            dir_header  = "🎯 Con @usuario (obligatorio)"
            opt_header  = "🎭 Con @usuario (opcional) o en solitario"
            solo_header = "🫂 En solitario"
            footer_text = "Usa /social para ver esta lista en cualquier momento"
        else:
            title       = "💞 Available social interactions"
            dir_header  = "🎯 With @user (required)"
            opt_header  = "🎭 With @user (optional) or solo"
            solo_header = "🫂 Solo"
            footer_text = "Use /social to see this list at any time"

        embed = discord.Embed(title=title, color=0xFF69B4)
        embed.add_field(name=dir_header,  value="\n".join(directed_lines),  inline=False)
        embed.add_field(name=opt_header,  value="\n".join(optional_lines),  inline=False)
        embed.add_field(name=solo_header, value="\n".join(solo_lines),      inline=False)
        embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed)
