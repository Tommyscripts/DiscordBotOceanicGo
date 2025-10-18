import os
import asyncio
import sys
import getpass
from typing import List, Set

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import sqlite3
import time
import random
import math
import logging
from datetime import date, datetime, timedelta

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    TOKEN = TOKEN.strip()
GUILD_ID = os.getenv("GUILD_ID")
APPLICATION_ID = os.getenv("APPLICATION_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_PERMISSIONS = os.getenv("BOT_PERMISSIONS", "3941734153713728")

# If no token found in environment, and we're in an interactive terminal, prompt the user
if not TOKEN:
    # Only prompt when running interactively
    if sys.stdin.isatty():
        print("DISCORD_TOKEN not set in environment.")
        print("You can paste your bot token now. It will be saved to a local .env file (not printed). Press Enter to cancel.")
        try:
            entered = getpass.getpass("DISCORD_TOKEN: ")
        except Exception:
            entered = None
        if entered:
            # write or update .env in project root
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            lines = []
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r") as f:
                        lines = f.readlines()
                except Exception:
                    lines = []
            # update existing DISCORD_TOKEN line if present
            updated = False
            for i, line in enumerate(lines):
                if line.strip().startswith("DISCORD_TOKEN="):
                    lines[i] = f"DISCORD_TOKEN={entered.strip()}\n"
                    updated = True
                    break
            if not updated:
                lines.append(f"DISCORD_TOKEN={entered.strip()}\n")
            try:
                with open(env_path, "w") as f:
                    f.writelines(lines)
                print(f"Saved token to {env_path}.")
            except Exception as e:
                print("Failed to save .env file:", e)
            TOKEN = entered
        else:
            print("No token entered. Exiting.")
            raise SystemExit(1)
    else:
        print("DISCORD_TOKEN not set in environment and input is not interactive. Copy .env.example to .env and set your token.")
        raise SystemExit(1)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Basic logging so we can see exceptions in hosted environments (Railway etc.)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')


# helper to run tasks safely and log uncaught exceptions
async def run_coro_safe(coro, name: str | None = None):
    try:
        await coro
    except Exception:
        logging.exception(f"Uncaught exception in background task {name}")


@bot.event
async def on_ready():
    try:
        logging.info(f"Bot ready. Logged in as: {bot.user} (id={getattr(bot.user, 'id', None)})")
        # attempt to sync commands and log the count
        try:
            synced = await bot.tree.sync()
            logging.info(f"Synced {len(synced)} application commands")
        except Exception as e:
            logging.warning(f"Failed to sync commands: {e}")
    except Exception:
        logging.exception("Exception in on_ready")

# ---------------- WORD CHAIN GAME (in-memory) ----------------
class WordChainGame:
    def __init__(self, channel: discord.TextChannel, starter: str | None = None, turn_timeout: int = 15):
        self.channel = channel
        self.players: list[int] = []  # join order
        self.lives: dict[int, int] = {}  # user_id -> lives
        self.used_words: set[str] = set()
        self.current_word: str | None = starter
        self.current_player_idx: int = 0
        self.turn_timeout = turn_timeout
        self.lock = asyncio.Lock()
        self.started = False
        self._turn_task: asyncio.Task | None = None
        # message id of the lobby message (so we can edit it to show current players)
        self.lobby_message_id: int | None = None

    def add_player(self, user_id: int) -> bool:
        if self.started:
            return False
        if user_id in self.players:
            return False
        self.players.append(user_id)
        self.lives[user_id] = 3
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id in self.players:
            self.players.remove(user_id)
            self.lives.pop(user_id, None)
            return True
        return False

    def next_player_id(self) -> int | None:
        if not self.players:
            return None
        # advance to next alive player
        starting_idx = self.current_player_idx % len(self.players)
        for i in range(len(self.players)):
            idx = (starting_idx + i) % len(self.players)
            uid = self.players[idx]
            if self.lives.get(uid, 0) > 0:
                self.current_player_idx = idx
                return uid
        return None

    def eliminate_if_needed(self, user_id: int):
        if self.lives.get(user_id, 0) <= 0 and user_id in self.players:
            # keep in list but effectively skipped; winner determination checks lives
            return True
        return False

    def alive_players(self) -> list[int]:
        return [uid for uid in self.players if self.lives.get(uid, 0) > 0]

    def is_word_valid(self, word: str) -> bool:
        # basic validation: alphabetical and not used
        if not word or not any(c.isalpha() for c in word):
            return False
        w = normalize_word(word)
        if w in self.used_words:
            return False
        if self.current_word:
            # must start with last letter of current_word
            last = normalize_word(self.current_word)[-1]
            return w[0] == last
        return True

    def play_word(self, user_id: int, word: str) -> tuple[bool, str]:
        # returns (accepted, message)
        w = normalize_word(word)
        if not self.is_word_valid(word):
            # lose a life
            self.lives[user_id] = max(0, self.lives.get(user_id, 0) - 1)
            return False, f"Invalid word. <@{user_id}> loses 1 life (now {self.lives[user_id]})."
        # accept
        self.used_words.add(w)
        self.current_word = w
        return True, f"Accepted: **{w}** — next player."

    def format_lobby(self) -> str:
        """Return a short text listing current players and their lives for lobby feedback."""
        if not self.players:
            return "No players yet. Click Join to participate."
        lines: list[str] = []
        for idx, uid in enumerate(self.players, start=1):
            lives = self.lives.get(uid, 0)
            lines.append(f"{idx}. <@{uid}> — {lives} lives")
        return "\n".join(lines)


def normalize_word(w: str) -> str:
    # Lowercase, strip punctuation except internal apostrophes/hyphens
    w = w.strip().lower()
    # remove surrounding non-alpha
    filtered = ''.join(ch for ch in w if ch.isalpha() or ch in "'-")
    # if result empty fallback to original letters only
    if not any(c.isalpha() for c in filtered):
        filtered = ''.join(c for c in w if c.isalpha())
    return filtered

# Active games per channel_id
wordchain_games: dict[int, WordChainGame] = {}


class WordChainView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = wordchain_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("No active lobby in this channel.", ephemeral=True)
            return
        added = game.add_player(interaction.user.id)
        if not added:
            await interaction.response.send_message("You can't join (maybe game started or already joined).", ephemeral=True)
            return
        await interaction.response.send_message(f"{interaction.user.mention} joined the lobby. Lives: 3", ephemeral=True)
        # update lobby message with current players
        if game.lobby_message_id and interaction.channel:
            try:
                lobby_msg = await interaction.channel.fetch_message(game.lobby_message_id)
                new_content = f"Word Chain lobby (host and players below):\n\n{game.format_lobby()}"
                await lobby_msg.edit(content=new_content, view=self)
            except Exception:
                pass

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = wordchain_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("No active lobby.", ephemeral=True)
            return
        removed = game.remove_player(interaction.user.id)
        if removed:
            await interaction.response.send_message("You left the lobby.", ephemeral=True)
            # update lobby message
            if game.lobby_message_id and interaction.channel:
                try:
                    lobby_msg = await interaction.channel.fetch_message(game.lobby_message_id)
                    new_content = f"Word Chain lobby (host and players below):\n\n{game.format_lobby()}"
                    await lobby_msg.edit(content=new_content, view=self)
                except Exception:
                    pass
        else:
            await interaction.response.send_message("You are not in the lobby.", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = wordchain_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("No active lobby.", ephemeral=True)
            return
        if game.started:
            await interaction.response.send_message("Game already started.", ephemeral=True)
            return
        if len(game.players) < 2:
            await interaction.response.send_message("Need at least 2 players to start.", ephemeral=True)
            return
        game.started = True
        await interaction.response.send_message("Game started! Play by sending words in this channel. You have 3 lives. Good luck!", ephemeral=False)
        # update lobby message to indicate game started and remove the view (disable buttons)
        if game.lobby_message_id and interaction.channel:
            try:
                lobby_msg = await interaction.channel.fetch_message(game.lobby_message_id)
                # stop the view to prevent further interactions
                try:
                    self.stop()
                except Exception:
                    pass
                new_content = f"Word Chain — GAME STARTED!\n\nPlayers:\n{game.format_lobby()}"
                await lobby_msg.edit(content=new_content, view=None)
            except Exception:
                pass
        # begin turn loop
        # run game in background but catch/log any uncaught exceptions
        asyncio.create_task(run_coro_safe(run_wordchain_game(game), name=f"wordchain-{game.channel.id}"))


async def run_wordchain_game(game: WordChainGame):
    channel = game.channel
    # Announce game start and ghosts award (100% probability)
    try:
        participants_total = len(game.players)
        ghosts_awarded = max(1, 2 * participants_total)
        await channel.send(f"Word Chain: the game is live! The first player will be chosen from the lobby. Winner will receive {GHOST_EMOJI} {ghosts_awarded}.")
    except Exception:
        await channel.send("Word Chain: the game is live! The first player will be chosen from the lobby.")
    # pick starting player index 0
    game.current_player_idx = 0
    # if no starter word, request first word from first player
    while True:
        alive = game.alive_players()
        if len(alive) <= 1:
            break
        uid = game.next_player_id()
        if uid is None:
            break
        member_mention = f"<@{uid}>"
        try:
            await channel.send(f"{member_mention}, it's your turn! You have {game.turn_timeout} seconds. Current word: {game.current_word or '(none)'}")
        except Exception:
            pass

        # wait for message from that user
        def check(m: discord.Message):
            return m.author.id == uid and m.channel.id == channel.id

        try:
            msg = await bot.wait_for('message', timeout=game.turn_timeout, check=check)
        except asyncio.TimeoutError:
            # lose a life
            game.lives[uid] = max(0, game.lives.get(uid, 0) - 1)
            await channel.send(f"Time's up! <@{uid}> loses 1 life (now {game.lives[uid]}).")
            # advance index to next player
            game.current_player_idx = (game.current_player_idx + 1) % max(1, len(game.players))
            continue

        word = msg.content.strip()
        accepted, text = game.play_word(uid, word)
        if accepted:
            await channel.send(f"{member_mention} played **{normalize_word(word)}**.")
        else:
            await channel.send(text)
        # check eliminated
        alive_after = game.alive_players()
        if len(alive_after) <= 1:
            break
        # advance to next player
        game.current_player_idx = (game.current_player_idx + 1) % max(1, len(game.players))

    # announce winner and award ghosts (always)
    survivors = game.alive_players()
    if survivors:
        winner = survivors[0]
        participants_total = len(game.players)
        ghosts_awarded = max(1, 2 * participants_total)
        try:
            guild = channel.guild if hasattr(channel, 'guild') else None
            if await is_staff_in_guild(guild, winner):
                try:
                    await channel.send(f"Game over! Winner is <@{winner}> 🎉 — Congrats! As staff you have unlimited {GHOST_EMOJI}.")
                except Exception:
                    pass
            else:
                add_ghosts(winner, ghosts_awarded)
                try:
                    await channel.send(f"Game over! Winner is <@{winner}> 🎉 — Congrats! You've won {GHOST_EMOJI} {ghosts_awarded}.")
                except Exception:
                    pass
        except Exception:
            try:
                await channel.send(f"Game over! Winner is <@{winner}> 🎉")
            except Exception:
                pass
    else:
        await channel.send("Game over! No winners — everyone lost their lives.")
    # cleanup
    try:
        del wordchain_games[channel.id]
    except KeyError:
        pass

# Slash command to create lobby and start game
@bot.tree.command(name="wordchain", description="Start a Word Chain game (join with buttons, start when ready)")
@app_commands.describe(timeout="Turn timeout in seconds (10-30). Default 15")
async def slash_wordchain(interaction: discord.Interaction, timeout: int = 15):
    # create a lobby message with Join/Leave/Start buttons
    if interaction.channel is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command must be used in a text channel.", ephemeral=True)
        return
    channel = interaction.channel
    if channel.id in wordchain_games:
        await interaction.response.send_message("There is already a lobby or game active in this channel.", ephemeral=True)
        return
    timeout = max(5, min(30, timeout))
    game = WordChainGame(channel=channel, starter=None, turn_timeout=timeout)
    wordchain_games[channel.id] = game
    view = WordChainView(channel_id=channel.id)
    # add host as first player automatically
    game.add_player(interaction.user.id)
    # send lobby message and remember its id so we can edit it on join/leave
    lobby_content = f"Word Chain lobby created by {interaction.user.mention}! Click Join to participate. Turn timeout: {timeout}s. Host auto-joined.\n\nPlayers:\n{game.format_lobby()}"
    resp = await interaction.response.send_message(lobby_content, view=view)
    # when using response.send_message, the returned object isn't the message; fetch it from the channel
    try:
        # followup fetch: the response message should be visible to the invoking user; try to get last message in channel from bot
        sent = await channel.fetch_message((await interaction.original_response()).id)
        game.lobby_message_id = sent.id
    except Exception:
        # best-effort: try to set lobby_message_id via the interaction response message
        try:
            orig = await interaction.original_response()
            game.lobby_message_id = orig.id
        except Exception:
            game.lobby_message_id = None

        # Help commands were previously defined inside the exception block above which
        # prevented them from being registered at module import time. Define them at
        # module level (outside of functions) below so the application command tree
        # picks them up correctly.

# If provided, set the application's ID on the bot (useful for some interactions)
if APPLICATION_ID:
    try:
        bot.application_id = int(APPLICATION_ID)
    except Exception:
        # keep as str if it isn't an int, but log for clarity
        print("Warning: APPLICATION_ID set but could not be converted to int. Keeping as string.")

# Public key is sometimes needed for verification of interactions in some frameworks.
# We just expose it here as a variable the rest of the code can use if needed.
# Ensure you put your values in a .env file like:
# DISCORD_TOKEN=your_token_here
# GUILD_ID=your_guild_id_here
# APPLICATION_ID=1424779352008298537
# PUBLIC_KEY=68188c9db80ddaa08f7b6540149c93bf4cfae9e38361018a093e245cd7db71f9

# In-memory storage mapping message_id -> set of user ids
tournaments: dict[int, Set[int]] = {}
# Additional metadata: map message_id -> dict with 'start' timestamp and 'host'
tournaments_meta: dict[int, dict] = {}

# In-memory storage for wheels (reaction-based roulette)
wheels: dict[int, Set[int]] = {}
wheels_meta: dict[int, dict] = {}

# SQLite for simple stats: wins per user (global) and per guild
# Path to SQLite DB. Allow overriding via environment variable FURBY_DB_PATH
# This helps when running in ephemeral environments (containers) or when you
# want the DB in a persistent location. If not set, fall back to repo-local
# `furby_stats.db` for backward compatibility.
DB_PATH = os.getenv("FURBY_DB_PATH") or os.path.join(os.path.dirname(__file__), "furby_stats.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wins_global (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wins_guild (
            guild_id INTEGER,
            user_id INTEGER,
            wins INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    # schedule entries for daily signups (date in ISO YYYY-MM-DD, slot 0-23)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_entries (
            date TEXT,
            slot INTEGER,
            user_id INTEGER,
            game TEXT,
            PRIMARY KEY (date, slot, user_id)
        )
        """
    )
    # Ghost currency balances
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ghosts_balances (
            user_id INTEGER PRIMARY KEY,
            ghosts INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # Shop items: guild_id NULL means global
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            role_id INTEGER,
            metadata TEXT
        )
        """
    )
    # Settings table to store per-guild configuration (e.g., staff role)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            staff_role_id INTEGER,
            mod_ban_role_id INTEGER,
            mod_kick_role_id INTEGER,
            mod_mute_role_id INTEGER
        )
        """
    )
    # moderation log
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mod_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            action TEXT,
            target_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()

init_db()

# Load available furby images (assets)
FURBY_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "furbys")
def load_furby_images():
    if not os.path.isdir(FURBY_ASSETS_DIR):
        return []
    files = [os.path.join(FURBY_ASSETS_DIR, f) for f in os.listdir(FURBY_ASSETS_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    return files

furby_image_files = load_furby_images()

def ensure_participant_images(msg_id: int, participants: list[int]):
    """Ensure each participant has an assigned image file. Returns a dict user_id -> image_path."""
    meta = tournaments_meta.setdefault(msg_id, {})
    image_map = meta.get("image_map") or {}
    # refresh available assets
    assets = load_furby_images()
    # assign for each participant if not already assigned
    for uid in participants:
        if uid in image_map and os.path.isfile(image_map[uid]):
            continue
        # prefer to reuse an asset if available
        chosen = None
        if assets:
            chosen = random.choice(assets)
        # else generate a placeholder image for this user
        if not chosen:
            # generate a simple placeholder image and save
            try:
                from PIL import Image, ImageDraw, ImageFont
            except Exception:
                chosen = None
            else:
                img = Image.new("RGBA", (400, 400), tuple([random.randint(100, 255) for _ in range(3)]))
                draw = ImageDraw.Draw(img)
                # draw simple eyes
                draw.ellipse((100-30, 120-30, 100+30, 120+30), fill=(255,255,255))
                draw.ellipse((300-30, 120-30, 300+30, 120+30), fill=(255,255,255))
                draw.ellipse((115-15, 135-15, 115+15, 135+15), fill=(0,0,0))
                draw.ellipse((315-15, 135-15, 315+15, 135+15), fill=(0,0,0))
                try:
                    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
                except Exception:
                    font = ImageFont.load_default()
                label = f"F-{str(uid)[-4:]}"
                # Compute text size robustly: prefer draw.textbbox, fall back to font.getsize
                try:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                except Exception:
                    try:
                        w, h = font.getsize(label)
                    except Exception:
                        w, h = (0, 0)
                draw.text(((400-w)/2, 320), label, fill=(0,0,0), font=font)
                out_path = os.path.join(FURBY_ASSETS_DIR, f"furby_user_{uid}.png")
                try:
                    os.makedirs(FURBY_ASSETS_DIR, exist_ok=True)
                    img.save(out_path)
                    chosen = out_path
                except Exception:
                    chosen = None
        image_map[uid] = chosen
    meta["image_map"] = image_map
    tournaments_meta[msg_id] = meta
    return image_map

# --------- Ghost currency helpers & shop ---------
GHOST_EMOJI = "👻"

def add_ghosts(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET ghosts = ghosts + ?", (user_id, amount, amount))
    conn.commit()
    conn.close()

def get_ghosts(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ghosts FROM ghosts_balances WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def set_ghosts(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO ghosts_balances(user_id, ghosts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET ghosts = ?", (user_id, amount, amount))
    conn.commit()
    conn.close()


async def is_staff_in_guild(guild: discord.Guild | None, user_id: int) -> bool:
    """Async: Return True if the given user_id represents a staff member in the guild.
    Staff is defined as having a configured staff role (preferred) or Manage Guild/Administrator permissions.
    """
    if not guild:
        return False
    gid = guild.id
    # check configured staff role first
    try:
        staff_role_id = get_staff_role(gid)
        if staff_role_id:
            # if the member has the role, they're staff
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            if member and any(r.id == staff_role_id for r in member.roles):
                return True
    except Exception:
        pass
    # fallback to permission check
    try:
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                return False
    except Exception:
        return False
    try:
        perms = member.guild_permissions
        return bool(perms.manage_guild or perms.administrator)
    except Exception:
        return False


def set_staff_role(guild_id: int, role_id: int | None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if role_id is None:
        cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = NULL", (guild_id, None))
    else:
        cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = ?", (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def get_staff_role(guild_id: int) -> int | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT staff_role_id FROM settings WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else None


def set_mod_role(guild_id: int, command: str, role_id: int | None):
    """Set role id for a moderation command (ban/kick/mute) in settings table."""
    field = None
    if command == 'ban':
        field = 'mod_ban_role_id'
    elif command == 'kick':
        field = 'mod_kick_role_id'
    elif command == 'mute':
        field = 'mod_mute_role_id'
    else:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if role_id is None:
        cur.execute(f"INSERT INTO settings(guild_id, {field}) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET {field} = NULL", (guild_id, None))
    else:
        cur.execute(f"INSERT INTO settings(guild_id, {field}) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET {field} = ?", (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def log_moderation(guild_id: int | None, action: str, target_id: int, moderator_id: int, reason: str | None = None):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO mod_log(guild_id, action, target_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (guild_id, action, target_id, moderator_id, reason, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_mod_role(guild_id: int, command: str) -> int | None:
    field = None
    if command == 'ban':
        field = 'mod_ban_role_id'
    elif command == 'kick':
        field = 'mod_kick_role_id'
    elif command == 'mute':
        field = 'mod_mute_role_id'
    else:
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT {field} FROM settings WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else None


async def has_mod_permission(interaction: discord.Interaction, command: str) -> bool:
    """Return True if the invoking user is allowed to run moderation command.
    Allowed if user is guild owner or has administrator/manage_guild or has the configured role for that command.
    """
    if not interaction.guild:
        return False
    # owner bypass
    try:
        if interaction.user.id == interaction.guild.owner_id:
            return True
    except Exception:
        pass
    # discord perms
    try:
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            member = await interaction.guild.fetch_member(interaction.user.id)
        perms = member.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        # check role
        role_id = get_mod_role(interaction.guild.id, command)
        if role_id:
            if any(r.id == role_id for r in member.roles):
                return True
    except Exception:
        pass
    return False


# Simple in-memory mute tracking: guild_id -> user_id -> unmute_timestamp
muted_until: dict[int, dict[int, float]] = {}


async def schedule_unmute_check():
    """Background task that periodically checks mutes and unmutes when time expires."""
    while True:
        now = time.time()
        to_unmute = []
        for gid, users in list(muted_until.items()):
            for uid, ts in list(users.items()):
                if ts <= now:
                    to_unmute.append((gid, uid))
        for gid, uid in to_unmute:
            try:
                guild = bot.get_guild(gid)
                if guild:
                    member = guild.get_member(uid) or await guild.fetch_member(uid)
                    # remove timeout (discord.py 2.3+: edit with timeout=None)
                    if member:
                        try:
                            await member.edit(timed_out_until=None)
                        except Exception:
                            # fallback: remove 'Muted' role if exists
                            muted_role = discord.utils.get(guild.roles, name='Muted')
                            if muted_role and muted_role in member.roles:
                                try:
                                    await member.remove_roles(muted_role)
                                except Exception:
                                    pass
                muted_until.get(gid, {}).pop(uid, None)
            except Exception:
                pass
        await asyncio.sleep(5)


@bot.event
async def on_connect():
    # start background unmute scheduler
    try:
        bot.loop.create_task(schedule_unmute_check())
    except Exception:
        pass


@bot.tree.command(name='ban', description='Ban a user by ID. Optional reason.')
@app_commands.describe(user_id='ID of the user to ban', reason='Optional reason')
async def slash_ban(interaction: discord.Interaction, user_id: str, reason: str | None = None):
    if not interaction.guild:
        await safe_reply(interaction, 'This command must be used in a guild (server).')
        return
    if not await has_mod_permission(interaction, 'ban'):
        await safe_reply(interaction, "You do not have permission to use this command.")
        return
    # try to resolve as member or id
    uid = None
    member = None
    if isinstance(user_id, str):
        # strip mention formatting
        cleaned = user_id.strip().lstrip('<@!').rstrip('>')
        try:
            uid = int(cleaned)
        except Exception:
            uid = None
    else:
        try:
            uid = int(user_id)
        except Exception:
            uid = None
    if uid is None:
        await safe_reply(interaction, 'Invalid user id or mention.')
        return
    try:
        # attempt to ban by object id (works even if user not in guild)
        await interaction.guild.ban(discord.Object(id=uid), reason=reason)
        log_moderation(interaction.guild.id, 'ban', uid, interaction.user.id, reason)
        await safe_reply(interaction, f'Banned <@{uid}>.')
    except Exception as e:
        await safe_reply(interaction, f'Failed to ban: {e}')


@bot.tree.command(name='kick', description='Kick a user by ID. Optional reason.')
@app_commands.describe(user_id='ID of the user to kick', reason='Optional reason')
async def slash_kick(interaction: discord.Interaction, user_id: str, reason: str | None = None):
    if not interaction.guild:
        await safe_reply(interaction, 'This command must be used in a guild (server).')
        return
    if not await has_mod_permission(interaction, 'kick'):
        await safe_reply(interaction, "You do not have permission to use this command.")
        return
    # resolve id
    cleaned = user_id.strip().lstrip('<@!').rstrip('>') if isinstance(user_id, str) else str(user_id)
    try:
        uid = int(cleaned)
    except Exception:
        await safe_reply(interaction, 'Invalid user id or mention.')
        return
    try:
        member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
        if not member:
            await safe_reply(interaction, 'Member not found in guild.')
            return
        await member.kick(reason=reason)
        log_moderation(interaction.guild.id, 'kick', member.id, interaction.user.id, reason)
        await safe_reply(interaction, f'Kicked {member.mention}.')
    except Exception as e:
        await safe_reply(interaction, f'Failed to kick: {e}')


@bot.tree.command(name='mute', description='Mute a user by ID for a duration. Optional reason. Time format: 10m, 2h, 1d')
@app_commands.describe(user_id='ID of the user to mute', duration='Duration like 10m, 2h, 1d (optional, default permanent)', reason='Optional reason')
async def slash_mute(interaction: discord.Interaction, user_id: str, duration: str | None = None, reason: str | None = None):
    if not interaction.guild:
        await safe_reply(interaction, 'This command must be used in a guild (server).')
        return
    if not await has_mod_permission(interaction, 'mute'):
        await safe_reply(interaction, "You do not have permission to use this command.")
        return
    cleaned = user_id.strip().lstrip('<@!').rstrip('>') if isinstance(user_id, str) else str(user_id)
    try:
        uid = int(cleaned)
    except Exception:
        await safe_reply(interaction, 'Invalid user id or mention.')
        return
    try:
        member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
        if not member:
            await safe_reply(interaction, 'Member not found in guild.')
            return
        # parse duration
        unmute_ts = None
        if duration:
            dur = duration.strip().lower()
            mult = 1
            if dur.endswith('m'):
                mult = 60
                val = dur[:-1]
            elif dur.endswith('h'):
                mult = 3600
                val = dur[:-1]
            elif dur.endswith('d'):
                mult = 3600 * 24
                val = dur[:-1]
            else:
                # assume seconds
                val = dur
            try:
                secs = int(val) * mult
                unmute_ts = time.time() + secs
            except Exception:
                await safe_reply(interaction, 'Invalid duration format.')
                return
        # prefer Discord timeout (mute) if available
        try:
            if unmute_ts:
                until = datetime.utcfromtimestamp(unmute_ts)
            else:
                until = None
            await member.edit(timed_out_until=until)
        except Exception:
            # fallback: add Muted role
            muted_role = discord.utils.get(interaction.guild.roles, name='Muted')
            if not muted_role:
                # try to create role
                try:
                    muted_role = await interaction.guild.create_role(name='Muted', reason='Create muted role for mute command')
                    # try to set permissions in channels
                    for ch in interaction.guild.channels:
                        try:
                            await ch.set_permissions(muted_role, send_messages=False, speak=False)
                        except Exception:
                            pass
                except Exception:
                    pass
            if muted_role:
                try:
                    await member.add_roles(muted_role, reason=reason)
                except Exception:
                    pass
        # record mute and log
        if unmute_ts:
            users = muted_until.setdefault(interaction.guild.id, {})
            users[member.id] = unmute_ts
        log_moderation(interaction.guild.id, 'mute', member.id, interaction.user.id, reason)
        await safe_reply(interaction, f'{member.mention} has been muted.')
    except Exception as e:
        await safe_reply(interaction, f'Failed to mute: {e}')


@bot.tree.command(name='settings_mod', description='Configure which role can use moderation commands (ban/kick/mute). Admins/owner only.')
@app_commands.describe(command='Which command to set (ban/kick/mute)', role='Role to allow (leave empty to unset)')
async def slash_settings_mod(interaction: discord.Interaction, command: str, role: discord.Role | None = None):
    # only allow owner or administrators
    if not interaction.guild:
        await safe_reply(interaction, 'This command must be used in a guild (server).')
        return
    try:
        member = interaction.guild.get_member(interaction.user.id) or await interaction.guild.fetch_member(interaction.user.id)
        perms = member.guild_permissions
        if not (interaction.user.id == interaction.guild.owner_id or perms.administrator):
            await safe_reply(interaction, 'Only the server owner or administrators may change moderation settings.')
            return
    except Exception:
        await safe_reply(interaction, 'Failed to check permissions.')
        return
    if command not in ('ban', 'kick', 'mute'):
        await safe_reply(interaction, 'Command must be one of: ban, kick, mute')
        return
    role_id = role.id if role else None
    try:
        set_mod_role(interaction.guild.id, command, role_id)
        if role_id:
            await safe_reply(interaction, f'Role {role.name} set for {command}.')
        else:
            await safe_reply(interaction, f'Role for {command} cleared.')
    except Exception as e:
        await safe_reply(interaction, f'Error updating settings: {e}')


async def safe_reply(interaction: discord.Interaction, content: str, ephemeral: bool = True):
    """Try to reply to an interaction. If response fails (unknown interaction or already responded),
    fallback to followup or channel send.
    """
    try:
        # prefer initial response
        if not interaction.response.is_done():
            await interaction.response.send_message(content, ephemeral=ephemeral)
            return
    except Exception:
        pass
    try:
        # try followup (if initial response already sent)
        await interaction.followup.send(content, ephemeral=ephemeral)
        return
    except Exception:
        pass
    try:
        # last resort: send in channel (not ephemeral)
        if interaction.channel:
            await interaction.channel.send(content)
            return
    except Exception:
        pass

def list_shop_items(guild_id: int | None = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if guild_id:
        cur.execute("SELECT id, name, price, role_id FROM shop_items WHERE guild_id = ?", (guild_id,))
    else:
        cur.execute("SELECT id, name, price, role_id FROM shop_items WHERE guild_id IS NULL")
    rows = cur.fetchall()
    conn.close()
    return rows

def add_shop_item(name: str, price: int, guild_id: int | None = None, role_id: int | None = None, metadata: str | None = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO shop_items(guild_id, name, price, role_id, metadata) VALUES (?, ?, ?, ?, ?)", (guild_id, name, price, role_id, metadata))
    conn.commit()
    conn.close()

def remove_shop_item(item_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM shop_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

def get_shop_item(item_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, guild_id, name, price, role_id, metadata FROM shop_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()
    return row

def maybe_halloween_announce(channel: discord.abc.GuildChannel):
    today = date.today()
    if today.month == 10 and 25 <= today.day <= 31:
        if random.random() < 0.25:
            try:
                asyncio.create_task(run_coro_safe(channel.send(f"Halloween event active! In this game the winner will receive {GHOST_EMOJI} ghosts."), name=f"halloween-announce-{getattr(channel, 'id', 'chan')}"))
            except Exception:
                pass

class TournamentView(discord.ui.View):
    def __init__(self, host: discord.Member | None = None, timeout: int | None = None):
        """A persistent view for the tournament. By default timeout is None so it won't auto-expire."""
        super().__init__(timeout=timeout)
        self.host = host

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # allow everyone to press buttons; you can add checks here
        return True

    @discord.ui.button(label="Join Tournament", style=discord.ButtonStyle.success, emoji="🏆")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Acknowledge quickly
        try:
            await interaction.response.send_message("You have joined the tournament.", ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send("You have joined the tournament.", ephemeral=True)
            except Exception:
                pass

        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        meta = tournaments_meta.get(msg_id, {})
        maxp = meta.get("max_participants", 50)

        if interaction.user.id in participants:
            # already joined
            try:
                await safe_reply(interaction, "You are already in the tournament.")
            except Exception:
                pass
            return
        if len(participants) >= maxp:
            try:
                await safe_reply(interaction, f"Tournament is full ({maxp} participants). You can't join.")
            except Exception:
                pass
            return

        participants.add(interaction.user.id)
        # build a small participant preview
        preview = "\n".join([f"<@{uid}>" for uid in list(participants)[:20]])
        try:
            await safe_reply(interaction, f"{interaction.user.mention} just joined the tournament.\nParticipants: {len(participants)}/{maxp}\n\n{preview}")
        except Exception:
            pass
        await update_tournament_message(interaction.message)

    @discord.ui.button(label="Leave Tournament", style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_message("You have left the tournament.", ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send("You have left the tournament.", ephemeral=True)
            except Exception:
                pass

        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        if interaction.user.id not in participants:
            try:
                await safe_reply(interaction, "You are not in the tournament.")
            except Exception:
                pass
            return
        participants.remove(interaction.user.id)
        meta = tournaments_meta.get(msg_id, {})
        maxp = meta.get("max_participants", 50)
        preview = "\n".join([f"<@{uid}>" for uid in list(participants)[:20]])
        try:
            await safe_reply(interaction, f"{interaction.user.mention} left the tournament.\nParticipants: {len(participants)}/{maxp}\n\n{preview if preview else 'No participants.'}")
        except Exception:
            pass
        await update_tournament_message(interaction.message)

    @discord.ui.button(label="Start Tournament", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Acknowledge start (non-ephemeral)
        try:
            await interaction.response.send_message("Tournament starting! 🔥", ephemeral=False)
        except Exception:
            try:
                await interaction.followup.send("Tournament starting! 🔥", ephemeral=False)
            except Exception:
                pass

        # Only host or users with manage_guild can start
        if self.host and interaction.user != self.host and not interaction.user.guild_permissions.manage_guild:
            try:
                await safe_reply(interaction, "Only the host or a manager can start the tournament.")
            except Exception:
                pass
            return

        msg_id = interaction.message.id
        participants = tournaments.get(msg_id, set())
        if len(participants) < 2:
            try:
                await safe_reply(interaction, "Need at least 2 participants to start.")
            except Exception:
                pass
            return

        # Start a fun battle simulation with messages in the channel.
        import random

        channel = interaction.channel

        # Acknowledge the interaction quickly
        try:
            await interaction.response.send_message("The tournament battle begins! 🔥", ephemeral=False)
        except Exception:
            # If we've already responded, ignore
            pass

        # Prepare battle state
        alive = list(participants)
        eliminated = []
        revived_once = set()
        meta = tournaments_meta.get(msg_id, {})
        max_revives = max(1, len(alive) // 10)  # limited number of revives (at least 1)
        revives_used = 0

        # Predefined goofy messages (English)
        attacks = [
            "{a} charges in and absolutely annihilates {d} with a glittery headbutt!",
            "{a} uses a supersonic squeak — {d} doesn't even see it coming.",
            "{a} performs the legendary Furby-Flick: {d} is flung into the void.",
            "{a} whispers 'tickle' and {d} mysteriously collapses laughing.",
        ]
        revives_msgs = [
            "But wait! {d} coughs up a spare battery and springs back to life!",
            "A mysterious fairy grants {d} a second chance — back in the fight!",
            "{d} finds a hidden extra life under its fluff and returns, enraged!",
        ]
        taunts = [
            "{a} taunts {d} with an evil giggle.",
            "{a} does a victory dance over {d}.",
        ]
        # Ensure each participant has an image assigned (consistent across the tournament)
        image_map = ensure_participant_images(msg_id, alive)

        # Battle loop: pairwise eliminations until one remains
        while len(alive) > 1:
            # pick two distinct combatants
            a, d = random.sample(alive, 2)
            # choose an attack message and maybe an image for attacker or defender
            msg_text = random.choice(attacks).format(a=f"<@{a}>", d=f"<@{d}>")
            # select images for attacker and defender if available
            attacker_img = image_map.get(a)
            defender_img = image_map.get(d)
            try:
                if attacker_img:
                    embed_msg = discord.Embed(description=msg_text)
                    try:
                        file = discord.File(attacker_img)
                        embed_msg.set_image(url=f"attachment://{os.path.basename(attacker_img)}")
                        await channel.send(embed=embed_msg, file=file)
                    except Exception:
                        await channel.send(msg_text)
                else:
                    await channel.send(msg_text)
            except discord.Forbidden:
                print(f"Warning: cannot send battle message in channel {getattr(channel, 'id', None)} - missing permissions.")
            except discord.HTTPException as e:
                print(f"Warning: failed to send battle message: {e}")

            # random cooldown between messages (5 to 10 seconds)
            await asyncio.sleep(random.uniform(5, 10))

            # determine outcome: d has a chance to be revived after death
            # For flavor, randomly decide who wins this encounter (attacker or defender)
            killer, victim = (a, d) if random.random() < 0.6 else (d, a)
            # victim is 'killed'
            if victim in alive:
                alive.remove(victim)
                eliminated.append(victim)
            # announce kill
            kill_texts = [
                f"{f'<@{killer}>'} lands the final blow — {f'<@{victim}>'} is out!",
                f"With dramatic flair, {f'<@{killer}>'} defeats {f'<@{victim}>'}.",
                f"{f'<@{victim}>'} was fluffed to bits by {f'<@{killer}>'}.",
            ]
            try:
                # use killer's image if available
                killer_img = image_map.get(killer)
                text = random.choice(kill_texts)
                if killer_img:
                    embed_kill = discord.Embed(description=text)
                    try:
                        file = discord.File(killer_img)
                        embed_kill.set_image(url=f"attachment://{os.path.basename(killer_img)}")
                        await channel.send(embed=embed_kill, file=file)
                    except Exception:
                        await channel.send(text)
                else:
                    await channel.send(text)
            except discord.Forbidden:
                print(f"Warning: cannot send kill message in channel {getattr(channel, 'id', None)} - missing permissions.")
            except discord.HTTPException as e:
                print(f"Warning: failed to send kill message: {e}")

            # chance to revive (60%) if revives left and the furby hasn't revived before
            if revives_used < max_revives and victim not in revived_once and random.random() < 0.6:
                revived_once.add(victim)
                revives_used += 1
                alive.append(victim)
                try:
                    rev_msg = random.choice(revives_msgs).format(d=f"<@{victim}>")
                    victim_img = image_map.get(victim)
                    if victim_img:
                        embed_rev = discord.Embed(description=rev_msg)
                        try:
                            file = discord.File(victim_img)
                            embed_rev.set_image(url=f"attachment://{os.path.basename(victim_img)}")
                            await channel.send(embed=embed_rev, file=file)
                        except Exception:
                            await channel.send(rev_msg)
                    else:
                        await channel.send(rev_msg)
                except discord.Forbidden:
                    print(f"Warning: cannot send revive message in channel {getattr(channel, 'id', None)} - missing permissions.")
                except discord.HTTPException as e:
                    print(f"Warning: failed to send revive message: {e}")
            else:
                # sometimes add a taunt or short comment
                if random.random() < 0.3:
                    try:
                        await channel.send(random.choice(taunts).format(a=f"<@{killer}>", d=f"<@{victim}>"))
                    except discord.Forbidden:
                        pass
                    except discord.HTTPException:
                        pass

            # short cooldown before next encounter
            await asyncio.sleep(random.uniform(5, 10))

        # Winner determined
        winner_id = alive[0]
        guild = interaction.guild

        # Save stats to SQLite
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # global
        cur.execute("INSERT INTO wins_global(user_id, wins) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET wins = wins + 1", (winner_id,))
        # guild
        if guild:
            cur.execute("INSERT INTO wins_guild(guild_id, user_id, wins) VALUES (?, ?, 1) ON CONFLICT(guild_id, user_id) DO UPDATE SET wins = wins + 1", (guild.id, winner_id))
        conn.commit()
        # fetch stats to show
        cur.execute("SELECT wins FROM wins_global WHERE user_id = ?", (winner_id,))
        global_wins = cur.fetchone()[0]
        guild_wins = 0
        if guild:
            cur.execute("SELECT wins FROM wins_guild WHERE guild_id = ? AND user_id = ?", (guild.id, winner_id))
            row = cur.fetchone()
            guild_wins = row[0] if row else 0
        conn.close()

        # compute duration
        meta = tournaments_meta.get(msg_id, {})
        start_ts = meta.get("start")
        duration_text = "unknown"
        if start_ts:
            dur = int(time.time() - start_ts)
            mins, secs = divmod(dur, 60)
            duration_text = f"{mins}m {secs}s"

        winner_mention = f"<@{winner_id}>"
        host_mention = f"<@{self.host.id}>" if self.host else "(unknown)"

        # Announce the winner and update UI
        try:
            await channel.send(f"Tournament finished! Winner: {winner_mention}. Host: {host_mention}")
        except discord.Forbidden:
            print(f"Warning: cannot send final announcement in channel {getattr(channel, 'id', None)} - missing permissions.")
        except discord.HTTPException as e:
            print(f"Warning: failed to send final announcement: {e}")

        # Award ghosts for the tournament: 2 ghosts per participant
        try:
            participants_total = len(participants)
            ghosts_awarded = 2 * participants_total
            # staff have unlimited ghosts (do not modify DB)
            try:
                if await is_staff_in_guild(interaction.guild, winner_id):
                    try:
                        await channel.send(f"{GHOST_EMOJI} {winner_mention} is staff and has unlimited ghosts — congratulations!")
                    except Exception:
                        pass
                else:
                    add_ghosts(winner_id, ghosts_awarded)
                    try:
                        await channel.send(f"{GHOST_EMOJI} {ghosts_awarded} ghosts have been awarded to {winner_mention}!")
                    except Exception:
                        pass
            except Exception:
                # fallback: attempt to award normally
                try:
                    add_ghosts(winner_id, ghosts_awarded)
                except Exception:
                    pass
        except Exception:
            pass

        # Optionally disable buttons after start
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            print(f"Warning: cannot edit view for message {interaction.message.id} - missing permissions.")
        except discord.HTTPException as e:
            print(f"Warning: failed to edit view for message {interaction.message.id}: {e}")

        # Edit embed to include results
        try:
            embed = interaction.message.embeds[0]
        except IndexError:
            embed = discord.Embed(title="Furby Tournament Results")

        results_field = (
            f"Winner: {winner_mention}\n"
            f"Host: {host_mention}\n"
            f"Duration: {duration_text}\n"
            f"Total wins (global): {global_wins}\n"
            f"Total wins (this server): {guild_wins}\n"
        )
        new_embed = embed.copy()
        new_embed.add_field(name="Results", value=results_field, inline=False)
        try:
            await interaction.message.edit(embed=new_embed)
        except discord.Forbidden:
            print(f"Warning: cannot edit message {interaction.message.id} to add results - missing permissions.")
        except discord.HTTPException as e:
            print(f"Warning: failed to edit message {interaction.message.id} to add results: {e}")

    @discord.ui.button(label="Cancel Tournament", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only host or users with manage_guild can cancel
        if self.host and interaction.user != self.host and not interaction.user.guild_permissions.manage_guild:
            try:
                await safe_reply(interaction, "Only the host or a manager can cancel the tournament.")
            except Exception:
                pass
            return
        msg_id = interaction.message.id
        tournaments.pop(msg_id, None)
        try:
            await safe_reply(interaction, "Tournament cancelled.")
        except Exception:
            pass
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            print(f"Warning: cannot edit view for message {interaction.message.id} - missing permissions.")
        except discord.HTTPException as e:
            print(f"Warning: failed to edit view for message {interaction.message.id}: {e}")


# ---------------- Slash commands: ghosts balance & shop ----------------
@bot.tree.command(name="ghosts", description="Check your ghost balance")
@app_commands.describe(user="User to check (optional)")
async def ghosts_balance(interaction: discord.Interaction, user: discord.User | None = None):
    target = user or interaction.user
    bal = get_ghosts(target.id)
    await interaction.response.send_message(f"{GHOST_EMOJI} {bal} ghosts — {target.mention}", ephemeral=True)


@bot.tree.command(name="give_ghosts", description="(Staff) Give ghosts to a user")
@app_commands.describe(target="Target user", amount="Amount of ghosts to give (can be negative)")
async def give_ghosts(interaction: discord.Interaction, target: discord.User, amount: int):
    # Only members with the configured staff role (or fallback perms) can use this
    try:
        guild = interaction.guild
        if not guild:
            await safe_reply(interaction, "This command must be used in a server.")
            return
        # check configured staff role or fallback permissions
        if not await is_staff_in_guild(guild, interaction.user.id):
            await safe_reply(interaction, "You are not authorized to give ghosts. Staff only.")
            return
        # proceed to give ghosts
        add_ghosts(target.id, amount)
        bal = get_ghosts(target.id)
        await safe_reply(interaction, f"{GHOST_EMOJI} {amount} ghosts given to {target.mention}. New balance: {bal}")
    except Exception as e:
        await safe_reply(interaction, f"Error giving ghosts: {e}")


shop_group = app_commands.Group(name="shop", description="Ghost shop commands")
try:
    bot.tree.add_command(shop_group)
except Exception:
    pass


@shop_group.command(name="list", description="List available shop items for this server or global ones")
async def shop_list(interaction: discord.Interaction):
    gid = interaction.guild.id if interaction.guild else None
    items = list_shop_items(gid)
    if not items:
        items = list_shop_items(None)
    if not items:
        await interaction.response.send_message("No shop items available.", ephemeral=True)
        return
    lines = []
    for row in items:
        item_id, name, price, role_id = row[0], row[1], row[2], row[3]
        role_part = f" (role: <@&{role_id}>)" if role_id else ""
        lines.append(f"{item_id}: {name} — {price} {GHOST_EMOJI}{role_part}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@shop_group.command(name="buy", description="Buy a shop item using ghosts")
@app_commands.describe(item_id="ID of the shop item to buy")
async def shop_buy(interaction: discord.Interaction, item_id: int):
    row = get_shop_item(item_id)
    if not row:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return
    _, guild_id, name, price, role_id, metadata = row
    # check guild scope
    if guild_id and (not interaction.guild or interaction.guild.id != guild_id):
        await interaction.response.send_message("This item is not available on this server.", ephemeral=True)
        return
    user_id = interaction.user.id
    bal = get_ghosts(user_id)
    if bal < price:
        await interaction.response.send_message(f"You don't have enough {GHOST_EMOJI}. You have {bal}, but the item costs {price}.", ephemeral=True)
        return
    # deduct
    add_ghosts(user_id, -price)
    # assign role if applicable
    if role_id and interaction.guild:
        try:
            role = interaction.guild.get_role(role_id) if isinstance(role_id, int) else None
            if role:
                try:
                    await interaction.user.add_roles(role)
                except Exception:
                    pass
        except Exception:
            pass
    await interaction.response.send_message(f"You bought **{name}** for {price} {GHOST_EMOJI}.", ephemeral=True)


@shop_group.command(name="add", description="(Admin) Add a shop item to this server or global")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(name="Item name", price="Price in ghosts", role="Optional role to grant")
async def shop_add(interaction: discord.Interaction, name: str, price: int, role: discord.Role | None = None, global_item: bool = False):
    gid = None if global_item else (interaction.guild.id if interaction.guild else None)
    role_id = role.id if role else None
    add_shop_item(name=name, price=price, guild_id=gid, role_id=role_id)
    await interaction.response.send_message(f"Added shop item: {name} — {price} {GHOST_EMOJI}", ephemeral=True)


@shop_group.command(name="remove", description="(Admin) Remove a shop item by id")
@app_commands.checks.has_permissions(manage_guild=True)
async def shop_remove(interaction: discord.Interaction, item_id: int):
    row = get_shop_item(item_id)
    if not row:
        await interaction.response.send_message("Item not found.", ephemeral=True)
        return
    remove_shop_item(item_id)
    await interaction.response.send_message(f"Removed shop item {item_id}.", ephemeral=True)


settings_group = app_commands.Group(name="settings", description="Server settings commands")
try:
    bot.tree.add_command(settings_group)
except Exception:
    pass


@settings_group.command(name="set_staff_role", description="(Owner) Configure the staff role for this server")
@app_commands.describe(role="Role to be considered staff. Omit to clear.")
async def settings_set_staff_role(interaction: discord.Interaction, role: discord.Role | None = None):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    # Only owner can set this
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("Only the server owner can set the staff role.", ephemeral=True)
        return
    try:
        role_id = role.id if role else None
        set_staff_role(interaction.guild.id, role_id)
        if role:
            await interaction.response.send_message(f"Staff role set to {role.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("Staff role cleared.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to set staff role: {e}", ephemeral=True)


@settings_group.command(name="get_staff_role", description="Show the configured staff role for this server")
async def settings_get_staff_role(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    try:
        role_id = get_staff_role(interaction.guild.id)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                await interaction.response.send_message(f"Configured staff role: {role.mention}", ephemeral=True)
                return
            else:
                await interaction.response.send_message(f"Configured staff role id: {role_id} (role not found on server)", ephemeral=True)
                return
        await interaction.response.send_message("No staff role configured.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to read staff role: {e}", ephemeral=True)
    

async def update_tournament_message(message: discord.Message):
    """Update the embed of the tournament message to reflect current participants."""
    msg_id = message.id
    participants = tournaments.get(msg_id, set())
    embed = message.embeds[0]
    # Rebuild the description with updated participant count and list
    base_description = embed.description.split("\n\n", 1)[0]
    # create a small participants list
    if participants:
        # show up to 50 in the embed, but cap visual list to 50
        part_lines = []
        for uid in list(participants)[:50]:
            part_lines.append(f"<@{uid}>")
        participants_text = "\n".join(part_lines)
    else:
        participants_text = "No participants yet."

    # include max participants info if available
    meta = tournaments_meta.get(msg_id, {})
    maxp = meta.get("max_participants")
    if maxp:
        full_text = " (FULL)" if len(participants) >= maxp else ""
        new_description = f"{base_description}\n\nParticipants ({len(participants)}/{maxp}){full_text}:\n{participants_text}"
    else:
        new_description = f"{base_description}\n\nParticipants ({len(participants)}):\n{participants_text}"
    new_embed = embed.copy()
    new_embed.description = new_description
    # Attempt to edit the message but handle missing permissions or HTTP errors gracefully
    try:
        # If message.author is available and not the bot, editing may fail with Forbidden
        # We still attempt to edit and catch exceptions to avoid crashing the view task
        await message.edit(embed=new_embed)
    except discord.Forbidden:
        # Bot lacks permission to edit this message (maybe original author is not the bot or channel perms)
        print(f"Warning: cannot edit message {msg_id} - missing permissions (403 Forbidden). Skipping embed update.")
    except discord.HTTPException as e:
        # Generic HTTP error from Discord
        print(f"Warning: failed to edit message {msg_id} due to HTTP error: {e}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Track users who react to a wheels message using the same emoji the bot reacted with.
    We only add users who reacted with the emoji that the bot used as its own reaction (stored in wheels_meta[msg_id]['emoji']).
    """
    try:
        msg_id = payload.message_id
        if msg_id not in wheels_meta:
            return
        meta = wheels_meta[msg_id]
        bot_emoji = meta.get("emoji")
        # Compare emoji by str; payload.emoji can be custom or unicode
        if str(payload.emoji) != str(bot_emoji):
            return
        # ignore reactions from the bot itself
        if payload.user_id == bot.user.id:
            return
        participants = wheels.setdefault(msg_id, set())
        participants.add(payload.user_id)
    except Exception as e:
        print("Error in on_raw_reaction_add:", e)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    try:
        msg_id = payload.message_id
        if msg_id not in wheels_meta:
            return
        meta = wheels_meta[msg_id]
        bot_emoji = meta.get("emoji")
        if str(payload.emoji) != str(bot_emoji):
            return
        participants = wheels.setdefault(msg_id, set())
        participants.discard(payload.user_id)
    except Exception as e:
        print("Error in on_raw_reaction_remove:", e)


# Create a command group for /wheels using app_commands.Group for compatibility
wheels_group = app_commands.Group(name="wheels", description="Create and run reaction-based wheels (roulette)")
try:
    # register group with the bot's tree
    bot.tree.add_command(wheels_group)
except Exception:
    # If registration fails here, it'll be picked up during sync in on_ready
    pass


@wheels_group.command(name="create", description="Create a wheel post. Users who react with the bot's emoji will join.")
@app_commands.describe(text="The announcement text for the wheel")
async def wheels_create(interaction: discord.Interaction, text: str):
    host = interaction.user
    embed = discord.Embed(title="Wheel", description=text, color=0x22AAFF)
    embed.add_field(name="Instructions", value="React with the same emoji the bot uses to join the wheel. The host can start with /wheels start.")
    embed.set_footer(text=f"Host: {host.display_name}")

    # Send the message and react with a default emoji (🎡)
    view = None
    try:
        await interaction.response.send_message(embed=embed, ephemeral=False)
    except Exception:
        # fallback
        await interaction.response.send_message(text, ephemeral=False)
    sent = await interaction.original_response()
    msg = await sent.fetch()

    # choose an emoji to react with; default to 🎡
    emoji = "🎡"
    try:
        await msg.add_reaction(emoji)
    except Exception:
        # ignore reaction failures
        pass

    # store wheels metadata
    wheels[msg.id] = set()
    wheels_meta[msg.id] = {
        "host": host.id,
        "emoji": emoji,
        "created_at": int(time.time()),
    }

    await interaction.followup.send(f"Wheel created. React with {emoji} to join.", ephemeral=True)


@wheels_group.command(name="start", description="Start the wheel and pick a random winner from reactors")
async def wheels_start(interaction: discord.Interaction):
    # Validate context
    # The command should be used after creating a wheel; find the most recent wheel by this host in the channel
    channel = interaction.channel
    host = interaction.user
    # find a wheel in this channel where host matches
    candidate = None
    for msg_id, meta in wheels_meta.items():
        if meta.get("host") == host.id:
            # ensure message is in same channel
            try:
                m = await channel.fetch_message(msg_id)
            except Exception:
                continue
            candidate = (msg_id, m, meta)
            break

    if not candidate:
        try:
            await interaction.response.send_message("No wheel created by you found in this channel.", ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send("No wheel created by you found in this channel.", ephemeral=True)
            except Exception:
                pass
        return

    msg_id, message_obj, meta = candidate
    participants = list(wheels.get(msg_id, set()))
    if not participants:
        try:
            await interaction.response.send_message("No one has joined the wheel.", ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send("No one has joined the wheel.", ephemeral=True)
            except Exception:
                pass
        return

    # Acknowledge start and generate a graphical wheel image
    # Announce spin and ghosts award (100% probability)
    participants_count = len(participants)
    ghosts_awarded = max(1, 2 * participants_count)
    try:
        await interaction.response.send_message(f"Spinning the wheel... 🎡 Winner will receive {GHOST_EMOJI} {ghosts_awarded}.", ephemeral=False)
    except Exception:
        try:
            await interaction.response.send_message("Spinning the wheel... 🎡", ephemeral=False)
        except Exception:
            try:
                await interaction.followup.send("Spinning the wheel... 🎡", ephemeral=False)
            except Exception:
                pass

    # Prepare names (limit to 24 slices for readability)
    max_slices = 24
    if len(participants) > max_slices:
        chosen_participants = random.sample(participants, max_slices)
    else:
        chosen_participants = participants[:]

    names = [f"{(await bot.fetch_user(uid)).display_name}" for uid in chosen_participants]

    # Choose winner among full participants (so image will point to one of shown participants if possible)
    winner_id = random.choice(participants)
    # If winner is not in the displayed slice, try to map it to a shown one by replacing a random slice
    if winner_id not in chosen_participants and len(chosen_participants) < len(participants):
        # replace a random slot with the winner so it's visible
        replace_idx = random.randrange(len(chosen_participants))
        chosen_participants[replace_idx] = winner_id
        names[replace_idx] = (await bot.fetch_user(winner_id)).display_name
    # Now find index of winner in chosen_participants (should exist)
    try:
        winner_index = chosen_participants.index(winner_id)
    except ValueError:
        # fallback: pick a visible index
        winner_index = random.randrange(len(chosen_participants))
        winner_id = chosen_participants[winner_index]

    # Generate animated GIF wheel using Pillow
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        Image = None

    img_path = None
    if Image:
        try:
            size = 800
            center = size // 2
            num = len(names)
            # generate distinct colors per participant using HSV spacing for good contrast
            try:
                import colorsys
                colors = []
                for i in range(num):
                    h = float(i) / max(1, num)
                    s = 0.85
                    v = 0.95
                    r, g, b = colorsys.hsv_to_rgb(h, s, v)
                    colors.append((int(r*255), int(g*255), int(b*255)))
            except Exception:
                # fallback to a small palette repeated if colorsys isn't available
                colors = [
                    (255,99,71),(60,179,113),(65,105,225),(238,130,238),(255,215,0),(70,130,180),
                    (255,165,0),(144,238,144),(199,21,133),(30,144,255),(218,165,32),(152,251,152)
                ]

            # base wheel image (transparent background)
            base = Image.new("RGBA", (size, size), (255,255,255,0))
            bdraw = ImageDraw.Draw(base)
            bbox = (20, 20, size-20, size-20)
            bdraw.ellipse(bbox, fill=(240,240,240), outline=(0,0,0))

            # draw wedges on base
            for i, nm in enumerate(names):
                start_angle = 360.0 * i / num
                end_angle = 360.0 * (i+1) / num
                color = colors[i % len(colors)]
                bdraw.pieslice(bbox, start=-start_angle, end=-end_angle, fill=color, outline=(255,255,255))

            # draw center circle
            center_radius = 80
            bdraw.ellipse((center-center_radius, center-center_radius, center+center_radius, center+center_radius), fill=(255,255,255), outline=(0,0,0))

            # render names around the wheel on a separate layer to avoid distortion when rotating
            labels = Image.new("RGBA", (size, size), (255,255,255,0))
            ldraw = ImageDraw.Draw(labels)
            # adaptive font sizing: favour larger font when fewer slices
            try:
                base_font_size = max(12, int(220 / max(4, num)))
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", base_font_size)
            except Exception:
                font = ImageFont.load_default()

            for i, nm in enumerate(names):
                start_angle = 360.0 * i / num
                end_angle = 360.0 * (i+1) / num
                mid_angle = (start_angle + end_angle) / 2
                r = int((size/2 - 60) * 0.8)
                theta = (mid_angle) * (math.pi/180.0)
                tx = int(center + r * -math.sin(theta))
                ty = int(center + r * -math.cos(theta))
                text = nm
                # truncate if too long
                max_len = 22
                if len(text) > max_len:
                    text = text[:max_len-1] + "…"
                # compute text size robustly: prefer draw.textbbox, fall back to font.getsize or font.getbbox
                try:
                    bbox = ldraw.textbbox((0, 0), text, font=font)
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
                            tw, th = (0, 0)
                # draw a semi-transparent rectangle behind the text to ensure readability over wedge colors
                pad_x = 10
                pad_y = 6
                rect_left = tx - tw//2 - pad_x
                rect_top = ty - th//2 - pad_y
                rect_right = tx + tw//2 + pad_x
                rect_bottom = ty + th//2 + pad_y
                # ensure coordinates are integers
                rect = (int(rect_left), int(rect_top), int(rect_right), int(rect_bottom))
                try:
                    ldraw.rectangle(rect, fill=(255,255,255,220))
                except Exception:
                    # fallback if alpha not supported
                    ldraw.rectangle(rect, fill=(255,255,255))
                # draw centered text on top of the rectangle
                ldraw.text((tx - tw//2, ty - th//2), text, font=font, fill=(0,0,0))

            # combine base + labels into a single wheel image
            wheel_img = Image.alpha_composite(base, labels)

            # gif frames: rotate the wheel so that it spins and lands on winner
            # compute target angle so that winner segment mid angle ends at top (0 degrees)
            target_mid = (360.0 * winner_index / num + 360.0 * (winner_index+1) / num) / 2
            # the wheel rotation is negative of segment angle (since pointer at top)
            target_rotation = -target_mid

            # generate frames: start from random offset and spin multiple turns decelerating
            start_rotation = random.uniform(0, 360)
            total_turns = random.uniform(3, 6)  # full rotations
            final_rotation = start_rotation + total_turns * 360 + target_rotation

            frames = []
            frame_count = 40
            for f in range(frame_count):
                t = f / (frame_count - 1)
                # ease out cubic
                ease = 1 - pow(1 - t, 3)
                rot = start_rotation + (final_rotation - start_rotation) * ease
                # rotate wheel_img around center
                frame = wheel_img.rotate(rot, resample=Image.BICUBIC, center=(center, center))
                # create full canvas with pointer and label area
                canvas = Image.new("RGBA", (size, size+80), (255,255,255,255))
                canvas.paste(frame, (0,0), frame)
                cdraw = ImageDraw.Draw(canvas)
                # draw pointer at top center
                pointer = [(center-24, 6), (center+24, 6), (center, 60)]
                cdraw.polygon(pointer, fill=(30,30,30))
                # draw winner label placeholder (will fill after frames)
                frames.append(canvas.convert("P"))

            # attach winner label to final frame
            try:
                font_sm = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
            except Exception:
                font_sm = ImageFont.load_default()
            winner_text = f"Winner: { (await bot.fetch_user(winner_id)).display_name }"
            final = frames[-1].convert("RGBA")
            fdraw = ImageDraw.Draw(final)
            # compute winner text size robustly: prefer textbbox, then font.getsize/getbbox
            try:
                bbox = fdraw.textbbox((0, 0), winner_text, font=font_sm)
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
                        wtw, wth = (0, 0)
            fdraw.rectangle(((size- wtw)//2 - 10, size - 60, (size+wtw)//2 + 10, size - 10), fill=(255,255,255,200))
            fdraw.text(((size-wtw)/2, size-55), winner_text, fill=(0,0,0), font=font_sm)
            frames[-1] = final.convert("P")

            # save GIF
            img_dir = os.path.join(os.path.dirname(__file__), ".temp")
            os.makedirs(img_dir, exist_ok=True)
            img_path = os.path.join(img_dir, f"wheel_{int(time.time())}.gif")
            # duration per frame in ms; with frame_count ~40 and 125ms gives ~5 seconds
            frames[0].save(img_path, save_all=True, append_images=frames[1:], duration=125, loop=0, optimize=False)
        except Exception as e:
            print("Failed to generate wheel image/gif:", e)
            img_path = None

    # send the generated image (or fallback text) and wait ~5 seconds
    try:
        if img_path and os.path.isfile(img_path):
            file = discord.File(img_path)
            await channel.send(content="The wheel spins... 🎡", file=file)
        else:
            # fallback simple announcement
            names_mention = " | ".join([f"<@{uid}>" for uid in chosen_participants])
            # if Pillow was missing, inform that image generation is unavailable
            if Image is None:
                await channel.send("Pillow (PIL) not available on this host — wheel image cannot be generated. Installing Pillow will enable a visual wheel.")
            await channel.send("Spinning: " + names_mention)
    except Exception:
        pass

    # short pause to simulate spinning (approx 5 seconds)
    await asyncio.sleep(5)

    # winner was selected earlier (winner_id) to ensure the image and announcement match
    winner_mention = f"<@{winner_id}>"

    # announce winner and mention them
    try:
        await channel.send(f"The wheel stops on... {winner_mention} 🎉\nCongratulations! You are the winner!")
    except Exception:
        await channel.send(f"The wheel stops on... {winner_mention} — Congratulations!")

    # Optionally record a win in DB (global)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO wins_global(user_id, wins) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET wins = wins + 1", (winner_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Award ghosts to the winner (unless staff)
    try:
        try:
            if await is_staff_in_guild(interaction.guild, winner_id):
                try:
                    await channel.send(f"{GHOST_EMOJI} {winner_mention} is staff and has unlimited ghosts — congratulations!")
                except Exception:
                    pass
            else:
                add_ghosts(winner_id, ghosts_awarded)
                try:
                    await channel.send(f"{GHOST_EMOJI} {ghosts_awarded} ghosts have been awarded to {winner_mention}!")
                except Exception:
                    pass
        except Exception:
            # fallback: award normally
            try:
                add_ghosts(winner_id, ghosts_awarded)
            except Exception:
                pass
    except Exception:
        pass

    # cleanup wheel data
    wheels.pop(msg_id, None)
    wheels_meta.pop(msg_id, None)


# ---------------- HAUNTED HOUSE (House) - Prototype ----------------
from uuid import uuid4
from typing import Optional

# In-memory storage for house games: game id string -> HouseGame (games are inferred by channel or host)
house_games: dict[str, dict] = {}


def find_game_by_channel(channel: discord.abc.Messageable | None) -> Optional["HouseGame"]:
    if not channel:
        return None
    for g in house_games.values():
        if g.channel_id == getattr(channel, 'id', None):
            return g
    return None


def find_lobby_game_by_host(user: discord.User | discord.Member) -> Optional["HouseGame"]:
    for g in house_games.values():
        if g.host_id == getattr(user, 'id', None) and g.state == 'lobby':
            return g
    return None


def find_pending_game_for_player(user: discord.User | discord.Member) -> Optional["HouseGame"]:
    # find a game where the user is invited but not accepted yet, prefer lobby
    for g in house_games.values():
        meta = g.players.get(getattr(user, 'id', None))
        if meta is not None and not meta.get('accepted'):
            return g
    return None


class HouseGame:
    def __init__(self, guild: discord.Guild, host_id: int, mode: str = "solo", max_players: int = 1):
        self.id = str(uuid4())[:8]
        self.guild = guild
        self.host_id = host_id
        self.mode = mode  # 'solo' or 'multi'
        self.max_players = max_players
        # players: user_id -> dict(accepted: bool, hp: int, inventory: list, position: room_id)
        self.players: dict[int, dict] = {host_id: {"accepted": True, "hp": 10, "inventory": [], "position": None}}
        self.state = "lobby"  # lobby | started | finished
        self.channel_id: int | None = None
        self.turn_index = 0
        self.map = {}  # simple map placeholder
        self.lock = asyncio.Lock()
        # internal flags to avoid spamming prompts
        self._sent_intro = False
        self._last_prompt_turn: int | None = None

    def init_map(self, width: int = 3, height: int = 3):
        """Initialize a simple rectangular map and place players in the center by default."""
        self.map = {"width": width, "height": height, "rooms": {}}
        for x in range(width):
            for y in range(height):
                # simple flavour descriptions; could be expanded later
                desc = f"A creaky room at ({x+1},{y+1}) with dusty floor and old wallpaper."
                # randomly vary a little
                if (x + y) % 3 == 0:
                    desc = f"A cold room at ({x+1},{y+1}) with a faint whispering sound."
                self.map["rooms"][(x, y)] = {"desc": desc, "items": []}
        # starting position: center
        sx = width // 2
        sy = height // 2
        for uid in list(self.players.keys()):
            self.players[uid]["position"] = (sx, sy)

    def valid_moves_for(self, uid: int) -> list[str]:
        pos = self.players.get(uid, {}).get("position")
        if not pos or not self.map:
            return []
        x, y = pos
        moves = []
        if y > 0:
            moves.append("up")
        if y < self.map.get("height", 0) - 1:
            moves.append("down")
        if x > 0:
            moves.append("left")
        if x < self.map.get("width", 0) - 1:
            moves.append("right")
        return moves

    def move_player(self, uid: int, direction: str) -> bool:
        pos = self.players.get(uid, {}).get("position")
        if not pos or not self.map:
            return False
        x, y = pos
        direction = direction.lower()
        if direction in ("up", "u") and y > 0:
            self.players[uid]["position"] = (x, y - 1)
            return True
        if direction in ("down", "d") and y < self.map.get("height", 0) - 1:
            self.players[uid]["position"] = (x, y + 1)
            return True
        if direction in ("left", "l") and x > 0:
            self.players[uid]["position"] = (x - 1, y)
            return True
        if direction in ("right", "r") and x < self.map.get("width", 0) - 1:
            self.players[uid]["position"] = (x + 1, y)
            return True
        return False

    def player_ids(self) -> list[int]:
        return list(self.players.keys())

    def accepted_players(self) -> list[int]:
        return [uid for uid, meta in self.players.items() if meta.get("accepted")]


house_group = app_commands.Group(name="house", description="Haunted House: solo or co-op private text adventures")


@house_group.command(name="create", description="Create a House game (creates a private channel).")
@app_commands.describe(mode="solo or multi", max_players="Max players for multi mode (ignored for solo)")
async def house_create(interaction: discord.Interaction, mode: str = "solo", max_players: int = 1):
    # Must be used in a guild
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server (guild).", ephemeral=True)
        return
    mode = mode.lower()
    if mode not in ("solo", "multi"):
        await interaction.response.send_message("Mode must be 'solo' or 'multi'.", ephemeral=True)
        return
    max_players = max(1, min(8, int(max_players)))
    # create game object
    game = HouseGame(guild=interaction.guild, host_id=interaction.user.id, mode=mode, max_players=max_players)
    house_games[game.id] = game

    # create a private text channel for the game, visible only to host and bot for now
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    try:
        ch = await interaction.guild.create_text_channel(name=f"house-{game.id}", overwrites=overwrites, reason="Private House game channel")
        game.channel_id = ch.id
    except discord.Forbidden:
        await interaction.response.send_message("Bot lacks permission to create channels. Please grant Manage Channels.", ephemeral=True)
        # clean up game
        house_games.pop(game.id, None)
        return
    except Exception as e:
        await interaction.response.send_message(f"Failed to create channel: {e}", ephemeral=True)
        house_games.pop(game.id, None)
        return

    # initialize a small map for the house
    game.init_map(width=3, height=3)

    await interaction.response.send_message(f"Created private House channel {ch.mention}. Invite players with `/house invite <user_id>` or mention. Mode: {mode}.", ephemeral=False)


# Subcommand to explain how to play 'house' (module-level so it registers)
@house_group.command(name="howto", description="Quick explanation of how to play Haunted House")
async def house_howto(interaction: discord.Interaction):
    text = (
        "**How to play House**\n"
        "1. Goal: Explore the house and complete the mission assigned by the host.\n"
        "2. Turns: In multi mode, players act in turns; follow host instructions.\n"
        "3. Interaction: Use the options the bot presents (respond, choose doors, use items).\n"
        "4. Penalties: Avoid invalid or out-of-turn actions to not lose progress.\n"
        "5. End: The game ends when a win condition is met or all players fail.\n\n"
        "Ask a moderator or check your server rules for server-specific variants."
    )
    try:
        await interaction.response.send_message(text, ephemeral=False)
    except Exception:
        try:
            if interaction.channel:
                await interaction.channel.send(text)
        except Exception:
            pass


# Top-level /mm command (module-level so it registers)
@bot.tree.command(name="mm", description="Quick explanation of how to play 'mm'")
async def slash_mm(interaction: discord.Interaction):
    """Respond with a short English explanation of how to play 'mm'."""
    text = (
        "**How to play MM**\n"
        "1. Goal: Complete the main mechanic of the mini-game 'mm' (e.g. guess, match, or compete).\n"
        "2. Start: Run `/mm` to see options or to begin a round if the bot allows.\n"
        "3. Common rules: Follow the prompts shown after starting a round (time limit, number of attempts, points for correct answers).\n"
        "4. Interaction: Reply in channel or use buttons/selections provided by the bot during the round.\n"
        "5. End: At the end of the round the winner will be announced and rewards distributed if applicable.\n\n"
        "For server-specific rules, ask a moderator or check the server's rules channel."
    )
    try:
        await interaction.response.send_message(text, ephemeral=False)
    except Exception:
        try:
            if interaction.channel:
                await interaction.channel.send(text)
        except Exception:
            pass


@house_group.command(name="invite", description="Invite a user to your House game (host only). Uses your active lobby.)")
@app_commands.describe(user="User ID or mention to invite")
async def house_invite(interaction: discord.Interaction, user: str):
    # infer the host's lobby game
    game = find_lobby_game_by_host(interaction.user)
    if not game:
        await interaction.response.send_message("Game not found.", ephemeral=True)
        return
    if interaction.user.id != game.host_id and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Only the host or a manager can invite.", ephemeral=True)
        return
    # Resolve user: accept either a mention (<@...>) or a raw numeric ID
    target_member = None
    cleaned = user.strip()
    # handle mention formats like <@12345> or <@!12345>
    if cleaned.startswith('<@') and cleaned.endswith('>'):
        cleaned = cleaned.lstrip('<@!').rstrip('>')
    # now if it's digits, try to fetch the member
    if cleaned.isdigit():
        try:
            uid = int(cleaned)
        except Exception:
            uid = None
        else:
            try:
                target_member = interaction.guild.get_member(uid) or await interaction.guild.fetch_member(uid)
            except Exception:
                target_member = None
    else:
        # try to resolve by name (fallback) - not ideal but best-effort
        try:
            # try to find by display name or name
            for m in interaction.guild.members:
                if m.display_name == cleaned or m.name == cleaned:
                    target_member = m
                    break
        except Exception:
            target_member = None

    if not target_member:
        await interaction.response.send_message("Could not resolve that user. Provide a valid user ID or mention.", ephemeral=True)
        return

    if target_member.id in game.players:
        await interaction.response.send_message(f"<@{target_member.id}> is already invited or joined.", ephemeral=True)
        return
    if len(game.players) >= game.max_players:
        await interaction.response.send_message("Game is full.", ephemeral=True)
        return
    if len(game.players) >= game.max_players:
        await interaction.response.send_message("Game is full.", ephemeral=True)
        return
    # add invited player as not accepted yet
    game.players[target_member.id] = {"accepted": False, "hp": 10, "inventory": [], "position": None}

    # DM the invite with instructions
    try:
        dm = await target_member.create_dm()
        try:
            await dm.send(f"You have been invited to the House game by {interaction.user.display_name}. To accept, run `/house accept` here or on the server. The game channel will be {interaction.guild.get_channel(game.channel_id).mention} once added.")
        except Exception:
            pass
    except Exception:
        # fallback: mention in the lobby channel
        pass

    await interaction.response.send_message(f"Invited <@{target_member.id}> to the game. They must accept with `/house accept`.", ephemeral=True)


@house_group.command(name="accept", description="Accept an invitation to a House game.")
async def house_accept(interaction: discord.Interaction):
    # infer the game where the user is invited or by channel
    game = find_pending_game_for_player(interaction.user) or find_game_by_channel(interaction.channel)
    if not game:
        await interaction.response.send_message("Game not found.", ephemeral=True)
        return
    if interaction.user.id not in game.players:
        await interaction.response.send_message("You have not been invited to this game.", ephemeral=True)
        return
    # mark accepted
    game.players[interaction.user.id]["accepted"] = True
    # give channel permission
    try:
        ch = game.guild.get_channel(game.channel_id)
        if ch:
            await ch.set_permissions(interaction.user, view_channel=True, send_messages=True)
    except Exception:
        pass
    await interaction.response.send_message(f"You joined the game. When the host starts, all accepted players will be present.", ephemeral=True)


@house_group.command(name="start", description="Start the House game (host only).")
async def house_start(interaction: discord.Interaction):
    # Prefer the host's lobby; fallback to channel
    game = find_lobby_game_by_host(interaction.user) or find_game_by_channel(interaction.channel)
    if not game:
        await interaction.response.send_message("Game not found. If you created the game, run this command as host or from the game's channel.", ephemeral=True)
        return
    if interaction.user.id != game.host_id and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Only the host or an administrator may start the game.", ephemeral=True)
        return
    if game.state != "lobby":
        await interaction.response.send_message("The game has already started or finished.", ephemeral=True)
        return
    accepted = game.accepted_players()
    if game.mode == "multi" and len(accepted) < 2:
        await interaction.response.send_message("At least 2 accepted players are needed for multiplayer mode.", ephemeral=True)
        return

    # lock and mark started
    game.state = "started"
    # ensure all accepted players have channel perms
    ch = game.guild.get_channel(game.channel_id) if game.channel_id else None
    if ch:
        for uid in accepted:
            try:
                member = await game.guild.fetch_member(uid)
                await ch.set_permissions(member, view_channel=True, send_messages=True)
            except Exception:
                pass
        # post intro with brief instructions and initial positions
        players_list = ', '.join([f'<@{u}>' for u in accepted])
    intro_lines = [f"Welcome to the Haunted House — session", f"Mode: {game.mode}", f"Players: {players_list}"]
    # show starting room description for each player
    for uid in accepted:
        pos = game.players[uid].get("position")
        if pos and game.map:
            x, y = pos
            room = game.map["rooms"].get((x, y))
            intro_lines.append(f"{f'<@{uid}>'} starts in room ({x+1},{y+1}): {room.get('desc') if room else 'An empty room.'}")
    intro_lines.append("When it's your turn you'll receive a prompt in this channel. Use `/house action move <direction>` or `/house action explore` or `/house action search`. Directions: up/down/left/right.")
    try:
        await ch.send("\n".join(intro_lines))
    except Exception:
        pass

    await interaction.response.send_message(f"Game started. See {ch.mention if ch else game.channel_id}.", ephemeral=False)
    # start simple turn loop task (run safely to log exceptions)
    asyncio.create_task(run_coro_safe(run_house_game(game), name=f"house-{game.id}"))


@house_group.command(name="action", description="Perform an action in the House game when it's your turn.")
@app_commands.describe(action="Action name: search|explore|move|use", target="Optional target (direction/item)")
async def house_action(interaction: discord.Interaction, action: str = "", target: str | None = None):
    # Infer game by channel (private game channel) or by being a participant
    game = find_game_by_channel(interaction.channel)
    if not game:
        # try to find a game where this user is a participant
        for g in house_games.values():
            if interaction.user.id in g.players:
                game = g
                break
    if not game:
        await interaction.response.send_message("Game not found. If you're in the game's private channel you can omit the game id.", ephemeral=True)
        return
    if game.state != "started":
        await interaction.response.send_message("Game has not started yet.", ephemeral=True)
        return
    if interaction.user.id not in game.players or not game.players[interaction.user.id].get("accepted"):
        await interaction.response.send_message("You are not a participant in this game.", ephemeral=True)
        return

    # simple turn enforcement: only the player whose turn it is may act
    accepted = game.accepted_players()
    if not accepted:
        await interaction.response.send_message("No active players.", ephemeral=True)
        return
    current_uid = accepted[game.turn_index % len(accepted)]
    if interaction.user.id != current_uid:
        await interaction.response.send_message(f"It's not your turn. It's <@{current_uid}>'s turn.", ephemeral=True)
        return

    # handle actions: search, explore, move, use, attack (basic)
    # normalize and be forgiving: strip whitespace, accept direction-only as move,
    # and accept common Spanish aliases and single-letter shortcuts.
    action = (action or "").strip().lower()
    # If user passed a bare direction as the action (e.g. `/house action up`) treat as move
    dir_aliases = {"up", "down", "left", "right", "u", "d", "l", "r",
                   "arriba", "abajo", "izquierda", "derecha", "arr", "abj", "izq", "der"}
    # Case A: user put direction in the action field
    if action in dir_aliases and not target:
        target = action
        action = "move"
    # Case B: user left action empty but provided a direction as target (common with slash UI)
    if (not action) and target:
        tnorm = (target or "").strip().lower()
        if tnorm in dir_aliases:
            action = "move"
            target = tnorm
    ch = game.guild.get_channel(game.channel_id) if game.channel_id else None

    # helper to send narration to game channel and ephemeral ack
    async def narrate(text: str):
        if ch:
            try:
                await ch.send(f"**{interaction.user.display_name}**: {text}")
            except Exception:
                pass
        await interaction.response.send_message("Action registered.", ephemeral=True)

    if action == "search":
        roll = random.random()
        if roll < 0.2:
            item = "ancient key"
            game.players[interaction.user.id]["inventory"].append(item)
            text = f"You search the room and find an **{item}**!"
        elif roll < 0.4:
            dmg = random.randint(1, 3)
            game.players[interaction.user.id]["hp"] -= dmg
            text = f"A hidden snare grazes you! You take {dmg} damage. (HP now {game.players[interaction.user.id]['hp']})"
        else:
            text = "You search but find nothing useful. The house groans..."
        await narrate(text)

    elif action == "explore":
        pos = game.players[interaction.user.id].get("position")
        if pos and game.map:
            x, y = pos
            room = game.map["rooms"].get((x, y), {})
            # show description and items, and available moves
            items = room.get("items", [])
            items_text = ", ".join(items) if items else "none"
            moves = game.valid_moves_for(interaction.user.id)
            text = f"You explore the room ({x+1},{y+1}): {room.get('desc', 'An empty room.')}. Items: {items_text}. You can move: {', '.join(moves) if moves else 'nowhere'}."
        else:
            text = "You feel disoriented. There's nothing here."
        await narrate(text)

    elif action == "move":
        if not target:
            await interaction.response.send_message("Specify a direction: up/down/left/right. Example: `/house action move up`", ephemeral=True)
            return
        dir = (target or "").strip().lower()
        # map Spanish/common aliases to canonical directions
        if dir in ("arriba", "u", "up", "arr"):
            dir = "up"
        elif dir in ("abajo", "d", "down", "abj"):
            dir = "down"
        elif dir in ("izquierda", "l", "left", "izq"):
            dir = "left"
        elif dir in ("derecha", "r", "right", "der"):
            dir = "right"
        moved = game.move_player(interaction.user.id, dir)
        if moved:
            pos = game.players[interaction.user.id]["position"]
            room = game.map["rooms"].get(pos, {})
            text = f"You move {dir} to room ({pos[0]+1},{pos[1]+1}). {room.get('desc', '')}"
        else:
            moves = game.valid_moves_for(interaction.user.id)
            text = f"Cannot move {dir}. Valid moves: {', '.join(moves) if moves else 'none'}."
        await narrate(text)

    elif action == "use":
        if not target:
            await interaction.response.send_message("Specify an item to use (example: `/house action use key`).", ephemeral=True)
            return
        item = target.lower()
        inv = game.players[interaction.user.id].get("inventory", [])
        if item in inv:
            # simple use: consume key to unlock something if present
            if item in ("ancient key", "key"):
                inv.remove(item)
                text = "You use the key. Somewhere a distant door unlocks with a creak..."
            else:
                text = f"You try to use {item} but nothing obvious happens."
        else:
            text = f"You don't have {item} in your inventory."
        await narrate(text)

    else:
        await interaction.response.send_message("Action not recognized. Supported: search, explore, move, use. When in game channel you can omit the game id.", ephemeral=True)
        return

    # advance turn
    game.turn_index = (game.turn_index + 1) % max(1, len(accepted))
    # reset prompt tracking so next turn will show prompt for new player
    game._last_prompt_turn = None


@house_group.command(name="move", description="Shortcut to move in the current House game (direction: up/down/left/right)")
@app_commands.describe(direction="Direction to move: up/down/left/right")
async def house_move(interaction: discord.Interaction, direction: str):
    # call house_action with move
    await house_action(interaction, action="move", target=direction)


@house_group.command(name="explore", description="Shortcut to explore the current room in the House game")
async def house_explore(interaction: discord.Interaction):
    await house_action(interaction, action="explore")


@house_group.command(name="status", description="Show game status")
async def house_status(interaction: discord.Interaction):
    game = find_game_by_channel(interaction.channel) or next((g for g in house_games.values() if interaction.user.id in g.players), None)
    if not game:
        await interaction.response.send_message("Game not found. If you're in the game's private channel you can omit the game id.", ephemeral=True)
        return
    players = "\n".join([f"<@{uid}> — HP: {meta['hp']} — Accepted: {meta['accepted']} — Pos: { (meta['position'][0]+1, meta['position'][1]+1) if meta.get('position') else 'N/A'}" for uid, meta in game.players.items()])
    ch = game.guild.get_channel(game.channel_id) if game.channel_id else None
    await interaction.response.send_message(f"Game {game.id}\nMode: {game.mode}\nState: {game.state}\nChannel: {ch.mention if ch else 'N/A'}\nPlayers:\n{players}", ephemeral=True)


@house_group.command(name="leave", description="Leave a House game")
async def house_leave(interaction: discord.Interaction):
    game = find_game_by_channel(interaction.channel) or next((g for g in house_games.values() if interaction.user.id in g.players), None)
    if not game:
        await interaction.response.send_message("Game not found. If you're in the game's private channel you can omit the game id.", ephemeral=True)
        return
    if interaction.user.id not in game.players:
        await interaction.response.send_message("You are not in this game.", ephemeral=True)
        return
    # remove player and revoke channel permission
    try:
        ch = game.guild.get_channel(game.channel_id)
        if ch:
            await ch.set_permissions(interaction.user, overwrite=None)
    except Exception:
        pass
    game.players.pop(interaction.user.id, None)
    await interaction.response.send_message(f"You left game {game.id}.", ephemeral=True)


@house_group.command(name="end", description="End a House game and remove the private channel (host only).")
async def house_end(interaction: discord.Interaction):
    game = find_game_by_channel(interaction.channel) or next((g for g in house_games.values() if g.host_id == interaction.user.id), None)
    if not game:
        await interaction.response.send_message("Game not found. If you're in the game's private channel you can omit the game id.", ephemeral=True)
        return
    if interaction.user.id != game.host_id and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Only the host or a manager can end the game.", ephemeral=True)
        return
    # Respond first so the interaction is acknowledged even if the channel is removed
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("Game ended and cleaned up.", ephemeral=True)
        else:
            await safe_reply(interaction, "Game ended and cleaned up.")
    except Exception:
        # fallback to safe_reply
        try:
            await safe_reply(interaction, "Game ended and cleaned up.")
        except Exception:
            pass

    # delete channel after acknowledging the interaction
    try:
        ch = game.guild.get_channel(game.channel_id)
        if ch:
            await ch.delete(reason="House game ended")
    except Exception:
        # ignore deletion errors (e.g., already deleted)
        pass

    # cleanup game from memory
    house_games.pop(game.id, None)


async def run_house_game(game: HouseGame):
    """Simple loop that posts turn prompts in the game's private channel."""
    try:
        ch = game.guild.get_channel(game.channel_id) if game.channel_id else None
        if not ch:
            return
        # use per-game flags to avoid spamming prompts
        if not hasattr(game, '_sent_intro'):
            game._sent_intro = False
        if not hasattr(game, '_last_prompt_turn'):
            game._last_prompt_turn = None
        while game.state == "started":
            accepted = game.accepted_players()
            if not accepted:
                await ch.send("No active players remain. Ending game.")
                break
            current_uid = accepted[game.turn_index % len(accepted)]
            # Build a concise prompt: mention player, show HP, position and valid moves
            meta = game.players.get(current_uid, {})
            hp = meta.get("hp", 0)
            pos = meta.get("position")
            pos_text = f"({pos[0]+1},{pos[1]+1})" if pos else "N/A"
            moves = game.valid_moves_for(current_uid)
            moves_text = ", ".join(moves) if moves else "none"
            prompt_lines = [f"It's <@{current_uid}>'s turn — HP: {hp} — Position: {pos_text}.", f"Valid moves: {moves_text}."]
            # only show brief guidance once at start to avoid spam
            if not game._sent_intro:
                prompt_lines.append("You can use `/house action move <direction>`, `/house action explore` or `/house action search`. You may omit the game id when in this channel.")
                game._sent_intro = True

            # avoid repeating the exact same prompt for the same player
            if game._last_prompt_turn == game.turn_index:
                # skip sending duplicate prompt
                pass
            else:
                try:
                    await ch.send(" ".join(prompt_lines))
                except Exception:
                    pass
                game._last_prompt_turn = game.turn_index

            # wait a limited time for the turn to be used; if no action, auto-pass
            await asyncio.sleep(20)

            # check if player still alive
            if game.players.get(current_uid, {}).get("hp", 0) <= 0:
                # mark removed and announce
                game.players[current_uid]["accepted"] = False
                try:
                    await ch.send(f"<@{current_uid}> has fallen and is out.")
                except Exception:
                    pass
                # do not increment turn_index relative to old accepted list --- recompute next
                # simply continue to next loop which will pick next accepted player
                continue

            # advance
            game.turn_index = (game.turn_index + 1) % max(1, len(accepted))
        game.state = "finished"
        try:
            await ch.send("The Haunted House session has ended. Thanks for playing!")
        except Exception:
            pass
    except Exception as e:
        print("Error in run_house_game:", e)

try:
    bot.tree.add_command(house_group)
except Exception:
    pass


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    # If we know the application id and desired permissions, print an invite URL for convenience
    try:
        app_id = getattr(bot, "application_id", None) or APPLICATION_ID
        if app_id:
            # ensure it's a string
            app_str = str(app_id)
            perms = BOT_PERMISSIONS
            invite_url = f"https://discord.com/oauth2/authorize?client_id={app_str}&scope=bot%20applications.commands&permissions={perms}"
            print(f"Invite URL: {invite_url}")
    except Exception:
        pass
    try:
        if GUILD_ID:
            synced = await bot.tree.sync(guild=discord.Object(id=int(GUILD_ID)))
        else:
            synced = await bot.tree.sync()
        try:
            names = [c.name for c in synced]
        except Exception:
            names = [getattr(c, 'name', str(c)) for c in synced]
        print(f"Synced {len(synced)} commands: {names}")
    except Exception as e:
        print("Failed to sync commands:", e)

@bot.tree.command(name="furby_tournament", description="Create a Furby tournament embed")
@app_commands.describe(title="Title for the tournament")
async def furbytournament(interaction: discord.Interaction, title: str = "Furby Tournament"):
    host = interaction.user
    embed = discord.Embed(title=title, color=0xF5A623)
    description = (
        "Tournament ID: furby-1234567890\n\n"
        "Instructions:\n"
        "• Click Join Tournament to enter your Furby\n"
        "• Tournament will be divided by levels\n"
        "• All Furbys will have max stats during battles\n"
        "• The host can start the tournament when ready\n"
        "• At least 2 Furbys of the same level are needed for that bracket\n"
        "• Maximum 50 participants allowed\n\n"
        "⚡ Revival System ⚡\n"
        "• Eliminated Furbys may get a second chance!\n"
        "• Revival checks occur at specific rounds\n"
        "• There's a 60% chance of revival occurring\n"
        "• Only a limited number of Furbys can be revived\n"
        "• Each Furby can only be revived once per tournament\n\n"
        "Lobby Timeout\n"
        "Today at "
    )
    embed.description = description + discord.utils.format_dt(discord.utils.utcnow(), style="t")
    embed.set_footer(text=f"Host: {host.display_name}")

    view = TournamentView(host=host, timeout=None)
    # Ensure the message is visible to everyone in the channel (not ephemeral)
    msg = await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
    # interaction.response.send_message returns None when deferred; fetch the message
    # so instead we use followup to get the message object
    sent = await interaction.original_response()
    tournaments[sent.id] = set()
    # store metadata: host id, start timestamp, and max participants
    tournaments_meta[sent.id] = {
        "host": host.id,
        "start": int(time.time()),
        "max_participants": 50,
    }


def _current_date_str():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _cleanup_old_schedule():
    """Remove schedule entries older than today (UTC-based daily reset)."""
    today = _current_date_str()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule_entries WHERE date < ?", (today,))
    conn.commit()
    conn.close()


schedule_group = app_commands.Group(name="schedule", description="Show or add schedule signups")


@schedule_group.command(name="show", description="Show today's schedule (24 slots)")
async def show_schedule(interaction: discord.Interaction):
    _cleanup_old_schedule()
    today = _current_date_str()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT slot, user_id, game FROM schedule_entries WHERE date = ? ORDER BY slot", (today,))
    rows = cur.fetchall()
    conn.close()

    # build a map slot -> list of entries
    slots = {i: [] for i in range(24)}
    for slot, user_id, game in rows:
        slots.setdefault(slot, []).append((user_id, game))

    # Build description with Discord timestamps: we will create a UTC timestamp for each slot (today at slot:00 UTC)
    desc_lines = []
    for hour in range(24):
        # compute unix ts for today at hour:00 UTC (for user's local display)
        struct = time.strptime(f"{today} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        ts = int(time.mktime(struct))
        time_token = f"<t:{ts}:t>"
        entries = slots.get(hour) or []
        if entries:
            entry_text = ", ".join([f"<@{uid}> ({game})" for uid, game in entries])
        else:
            entry_text = "(empty)"
        # display slot number 1..24 on the left for simpler selection
        slot_label = hour + 1
        desc_lines.append(f"**{slot_label}** — {time_token} : {entry_text}")

    embed = discord.Embed(title="Schedule (24h)", description="\n".join(desc_lines), color=0x00BFFF)
    await interaction.response.send_message(embed=embed, ephemeral=False)


@schedule_group.command(name="add", description="Add yourself to a numbered slot (1-24)")
@app_commands.describe(slot="Slot number 1-24", game="Game or note to add")
async def add_schedule(interaction: discord.Interaction, slot: int, game: str):
    # normalize slot to 1-24 and convert to 0-23 index for storage
    if slot < 1 or slot > 24:
        await interaction.response.send_message("Please provide a slot number between 1 and 24.", ephemeral=True)
        return
    time = slot - 1

    # Use UTC date to store daily entries that reset every 24h at midnight UTC
    today = _current_date_str()
    _cleanup_old_schedule()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Upsert: allow multiple users per slot; prevent duplicate same user in same slot
    try:
        cur.execute("INSERT OR IGNORE INTO schedule_entries(date, slot, user_id, game) VALUES (?, ?, ?, ?)", (today, time, interaction.user.id, game))
        conn.commit()
    except Exception as e:
        print("DB error adding schedule:", e)
    finally:
        conn.close()

    # show user the friendly slot number and the UTC hour
    display_slot = time + 1
    await interaction.response.send_message(f"Added you to slot {display_slot} ({time:02d}:00 UTC) for '{game}'. Use `/schedule show` to view.", ephemeral=True)


# register the group with the bot's command tree
try:
    bot.tree.add_command(schedule_group)
except Exception:
    # in case adding twice or running in reload scenarios
    pass


@schedule_group.command(name="delete", description="Remove your signup from a numbered slot (1-24)")
@app_commands.describe(slot="Slot number 1-24 to remove your signup from")
async def delete_schedule(interaction: discord.Interaction, slot: int):
    """Delete the invoking user's signup for the given slot (UTC date: today)."""
    # validate slot
    if slot < 1 or slot > 24:
        await interaction.response.send_message("Please provide a slot number between 1 and 24.", ephemeral=True)
        return
    time_idx = slot - 1

    today = _current_date_str()
    _cleanup_old_schedule()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM schedule_entries WHERE date = ? AND slot = ? AND user_id = ?", (today, time_idx, interaction.user.id))
        deleted = cur.rowcount
        conn.commit()
    except Exception as e:
        print("DB error deleting schedule:", e)
        deleted = 0
    finally:
        conn.close()

    if deleted:
        await interaction.response.send_message(f"Removed your signup from slot {slot} ({time_idx:02d}:00 UTC). Use `/schedule show` to view.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No signup found for you in slot {slot}. Use `/schedule show` to check current signups.", ephemeral=True)


@bot.tree.command(name="resync_commands", description="Force re-sync of commands in this guild (admins only)")
@app_commands.checks.has_permissions(manage_guild=True)
async def resync_commands(interaction: discord.Interaction):
    # Only works in a guild context
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a guild.", ephemeral=True)
        return
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=interaction.guild.id))
        await interaction.response.send_message(f"Synced {len(synced)} commands in this guild.", ephemeral=True)
        print(f"Manual resync in guild {interaction.guild.id}: {[c.name for c in synced]}")
    except Exception as e:
        await interaction.response.send_message(f"Resync failed: {e}", ephemeral=True)

# ...existing code...

if __name__ == "__main__":
    # Try to run the bot, but if the token is invalid prompt up to 3 times to re-enter
    import discord as _discord

    max_attempts = 3
    attempts = 0
    while attempts < max_attempts:
        if not TOKEN:
            print("DISCORD_TOKEN not set. Please enter a token now (or set DISCORD_TOKEN in env/.env):")
            try:
                entered = getpass.getpass("DISCORD_TOKEN: ")
            except Exception:
                entered = None
            if not entered:
                print("No token entered. Exiting.")
                raise SystemExit(1)
            TOKEN = entered.strip()
            # persist to .env
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            lines = []
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r") as f:
                        lines = f.readlines()
                except Exception:
                    lines = []
            updated = False
            for i, line in enumerate(lines):
                if line.strip().startswith("DISCORD_TOKEN="):
                    lines[i] = f"DISCORD_TOKEN={TOKEN}\n"
                    updated = True
                    break
            if not updated:
                lines.append(f"DISCORD_TOKEN={TOKEN}\n")
            try:
                with open(env_path, "w") as f:
                    f.writelines(lines)
                print(f"Saved token to {env_path}.")
            except Exception as e:
                print("Failed to save .env file:", e)

        try:
            bot.run(TOKEN)
            break
        except _discord.errors.LoginFailure:
            attempts += 1
            print(f"Login failed (invalid token). Attempts left: {max_attempts - attempts}")
            # Clear TOKEN to force re-prompt
            TOKEN = None
            if attempts >= max_attempts:
                print("Maximum login attempts reached. Exiting.")
                raise SystemExit(1)
            # loop will prompt again
