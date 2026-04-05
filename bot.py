from __future__ import annotations
import os
import asyncio
import sys
import getpass
from typing import List, Set, Optional
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import psycopg2
import time
import random
import math
import logging
import shutil
from pathlib import Path
import calendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones as _all_tz_fn
from io import BytesIO

# Duck game module
from duck_game import generate_duck, duck_to_bytes, random_duck, fight_ducks, Duck

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

# In-memory store to track channels locked by the bot and previous overwrites
locked_channels: dict[int, dict[tuple[str, int], dict[str, bool | None]]] = {}

# Global lock to serialize permission-modifying operations to avoid concurrent PUT bursts
permission_op_lock = asyncio.Lock()

# Basic logging so we can see exceptions in hosted environments (Railway etc.)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')


# helper to run tasks safely and log uncaught exceptions
async def run_coro_safe(coro, name: str | None = None):
    try:
        await coro
    except Exception:
        logging.exception(f"Uncaught exception in background task {name}")



async def end_game(game: "HouseGame", announce: bool = True, delete_channel: bool = False):
    """Cleanly end a House game: announce, revoke permissions, optionally delete channel and remove game from memory.

    If the game has a 'winner' key in its map (or a caller provides a winner via
    game._last_winner_display_name), include that in the announcement.
    """
    try:
        ch = game.guild.get_channel(game.channel_id) if game.channel_id else None
        # build announcement message
        winner_name = getattr(game, '_last_winner_display_name', None)
        if announce and ch:
            try:
                if winner_name:
                    await ch.send(f"{winner_name} unlocked the door and escaped! The Haunted House session has ended. Thanks for playing!")
                else:
                    await ch.send("The Haunted House session has ended. Thanks for playing!")
            except Exception:
                pass
        # revoke channel permissions for players
        if ch:
                try:
                    # Remove member-specific overwrites for all players in a single edit
                    current_overwrites = dict(ch.overwrites)
                    modified = False
                    # keys in current_overwrites can be Role, Member, or User
                    for uid in list(game.players.keys()):
                        for target in list(current_overwrites.keys()):
                            try:
                                if hasattr(target, 'id') and getattr(target, 'id') == uid:
                                    current_overwrites.pop(target, None)
                                    modified = True
                            except Exception:
                                pass
                    if modified:
                        async with permission_op_lock:
                            try:
                                await ch.edit(overwrites=current_overwrites)
                            except Exception:
                                # fallback to per-member removal if edit fails
                                for uid in list(game.players.keys()):
                                    try:
                                        member = await game.guild.fetch_member(uid)
                                        await ch.set_permissions(member, overwrite=None)
                                    except Exception:
                                        pass
                    else:
                        # nothing to change via edit; try per-member removal to be safe
                        for uid in list(game.players.keys()):
                            try:
                                member = await game.guild.fetch_member(uid)
                                await ch.set_permissions(member, overwrite=None)
                            except Exception:
                                pass
                except Exception:
                    # best-effort per-member cleanup
                    for uid in list(game.players.keys()):
                        try:
                            member = await game.guild.fetch_member(uid)
                            await ch.set_permissions(member, overwrite=None)
                        except Exception:
                            pass
        # optionally delete the channel
        if delete_channel and ch:
            try:
                await ch.delete(reason="House game ended")
            except Exception:
                pass
    finally:
        # remove game from in-memory registry
        try:
            house_games.pop(game.id, None)
        except Exception:
            pass

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
    # Announce game start and turkeys award (100% probability)
    try:
        participants_total = len(game.players)
        turkeys_awarded = max(1, 2 * participants_total)
        await channel.send(f"Word Chain: the game is live! The first player will be chosen from the lobby. Winner will receive {fmt_currency(getattr(channel.guild, 'id', None), turkeys_awarded)}.")
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

    # announce winner and award turkeys (always)
    survivors = game.alive_players()
    if survivors:
        winner = survivors[0]
        participants_total = len(game.players)
        turkeys_awarded = max(1, 2 * participants_total)
        try:
            guild = channel.guild if hasattr(channel, 'guild') else None
            if await is_staff_in_guild(guild, winner):
                try:
                    emoji, name = get_currency_display(getattr(channel.guild, 'id', None))
                    await channel.send(f"Game over! Winner is <@{winner}> 🎉 — Congrats! As staff you have unlimited {emoji} {name}.")
                except Exception:
                    pass
            else:
                add_turkeys(getattr(channel.guild, 'id', 0) or 0, winner, turkeys_awarded)
                try:
                    await channel.send(f"Game over! Winner is <@{winner}> 🎉 — Congrats! You've won {fmt_currency(getattr(channel.guild, 'id', None), turkeys_awarded)}.")
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

# PostgreSQL connection URL — set DATABASE_URL in your .env file.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set in environment. Please add it to your .env file.")
    raise SystemExit(1)

def get_db_conn():
    """Return a new psycopg2 connection. Caller is responsible for closing it."""
    return psycopg2.connect(DATABASE_URL)

# (SQLite file migration removed — using PostgreSQL)

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wins_global (
            user_id BIGINT PRIMARY KEY,
            wins INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wins_guild (
            guild_id BIGINT,
            user_id BIGINT,
            wins INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_entries (
            date TEXT,
            slot INTEGER,
            guild_id BIGINT,
            user_id BIGINT,
            game TEXT,
            local_tz TEXT NOT NULL DEFAULT 'Etc/UTC',
            local_slot INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, slot, guild_id, user_id)
        )
        """
    )
    # Migration: ensure existing installations get a guild_id column and composite PK
    try:
        cur.execute("ALTER TABLE schedule_entries ADD COLUMN IF NOT EXISTS guild_id BIGINT NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE schedule_entries ADD COLUMN IF NOT EXISTS local_tz TEXT NOT NULL DEFAULT 'Etc/UTC'")
        cur.execute("ALTER TABLE schedule_entries ADD COLUMN IF NOT EXISTS local_slot INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE schedule_entries DROP CONSTRAINT IF EXISTS schedule_entries_pkey")
        cur.execute("ALTER TABLE schedule_entries ADD PRIMARY KEY (date, slot, guild_id, user_id)")
    except Exception:
        # best-effort migration; ignore errors (e.g., running on SQLite or unsupported PG version)
        pass
    # Economy: per-guild balances (same user has separate balances per server)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS turkeys_balances (
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            turkeys INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_items (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            role_id BIGINT,
            metadata TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            guild_id BIGINT PRIMARY KEY,
            staff_role_id BIGINT,
            mod_ban_role_id BIGINT,
            mod_kick_role_id BIGINT,
            mod_mute_role_id BIGINT,
            currency_display_name TEXT,
            currency_emoji TEXT,
            official_links_channel_id BIGINT,
            currency_command_name TEXT,
            language TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS official_links (
            guild_id BIGINT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (guild_id, name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mod_log (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT,
            action TEXT,
            target_id BIGINT,
            moderator_id BIGINT,
            reason TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_commands (
            guild_id BIGINT,
            name TEXT NOT NULL,
            info TEXT NOT NULL,
            PRIMARY KEY (guild_id, name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS monopoly_go_config (
            guild_id BIGINT PRIMARY KEY,
            channel_id BIGINT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS monopoly_go_posted (
            url TEXT PRIMARY KEY,
            posted_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS easter_egg_scores (
            guild_id BIGINT,
            user_id BIGINT,
            username TEXT,
            egg_count INT NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id BIGINT PRIMARY KEY,
            timezone TEXT NOT NULL
        )
        """
    )
    # Add time_format column if it doesn't exist yet (migration for existing tables)
    cur.execute(
        """
        ALTER TABLE user_timezones
            ADD COLUMN IF NOT EXISTS time_format TEXT NOT NULL DEFAULT '24h'
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

# Teddy assets (separate set)
TEDDY_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "teddy wars")
def load_teddy_images():
    if not os.path.isdir(TEDDY_ASSETS_DIR):
        return []
    files = [os.path.join(TEDDY_ASSETS_DIR, f) for f in os.listdir(TEDDY_ASSETS_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    return files

teddy_image_files = load_teddy_images()

def get_special_teddy_images(prefix: str):
    """Return teddy asset paths whose basename starts with `prefix` (case-insensitive)."""
    assets = load_teddy_images()
    p = prefix.lower()
    return [a for a in assets if os.path.basename(a).lower().startswith(p)]

def ensure_teddy_images(msg_id: int, participants: list[int]):
    """Ensure each participant has an assigned teddy image file. Returns a dict user_id -> image_path."""
    meta = tournaments_meta.setdefault(msg_id, {})
    image_map = meta.get("teddy_image_map") or {}
    # refresh available assets
    assets = load_teddy_images()
    # assign for each participant if not already assigned
    for uid in participants:
        if uid in image_map and os.path.isfile(image_map[uid]):
            continue
        chosen = None
        if assets:
            chosen = random.choice(assets)
        # else generate a placeholder image for this user
        if not chosen:
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
                label = f"T-{str(uid)[-4:]}"
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
                out_path = os.path.join(TEDDY_ASSETS_DIR, f"teddy_user_{uid}.png")
                try:
                    os.makedirs(TEDDY_ASSETS_DIR, exist_ok=True)
                    img.save(out_path)
                    chosen = out_path
                except Exception:
                    chosen = None
        image_map[uid] = chosen
    meta["teddy_image_map"] = image_map
    tournaments_meta[msg_id] = meta
    return image_map

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

# --------- Turkey currency helpers & shop ---------
TURKEY_EMOJI = "🦃"

# Currency display defaults (front only): do NOT change DB balance naming.
DEFAULT_CURRENCY_NAME = "Snuggles"
DEFAULT_CURRENCY_EMOJI = TURKEY_EMOJI

# --------- Command descriptions (en / es) ---------
# Keys for groups use the pattern "__<group>__"; subcommands use "<group>.<sub>".
COMMAND_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "en": {
        # Top-level
        "wordchain": "Start a Word Chain game (join with buttons, start when ready)",
        "ban": "Ban a user by ID. Optional reason.",
        "kick": "Kick a user by ID. Optional reason.",
        "mute": "Mute a user by ID for a duration. Optional reason. Time format: 10m, 2h, 1d",
        "settings_mod": "Configure which role can use moderation commands (ban/kick/mute). Admins/owner only.",
        "snuggles": "Check your Snuggles balance",
        "give_snuggles": "(Staff) Give Snuggles to a user",
        "rename_currency": "(Staff) Change the display name and/or emoji of the currency",
        "mm": "Quick explanation of how to play 'mm'",
        "setmonopolychannel": "Set the channel where Monopoly GO free reward links will be posted",
        "unsetmonopolychannel": "Disable automatic Monopoly GO reward link posting in this server",
        "custom": "Create a custom command for this server",
        "deletecustom": "Delete a custom command from this server",
        "set_official_links_channel": "Set the channel where official links will be posted",
        "add_official_link": "Add an official link (e.g.: free dice/shield)",
        "remove_official_link": "Remove an official link by name",
        "list_official_links": "List the saved official links for this server",
        "post_official_links": "Post official links in the configured channel (or this channel if none set)",
        "resync_commands": "Force re-sync of commands in this guild (admins only)",
        "setmytime": "Save your timezone so /time also shows your local time",
        "settimeformat": "Choose how to display the time: 24h (military) or 12h (AM/PM)",
        "time": "Show the current time in any timezone, or compare with another user",
        # Groups
        "__shop__": "Shop commands",
        "__settings__": "Server settings commands",
        "__m__": "Moderation utilities",
        "__wheels__": "Create and run reaction-based wheels (roulette)",
        "__house__": "Haunted House: solo or co-op private text adventures",
        "__schedule__": "Show or add schedule signups",
        # Subcommands
        "shop.list": "List available shop items for this server or global ones",
        "shop.buy": "Buy a shop item using Snuggles",
        "shop.add": "(Admin) Add a shop item to this server or global",
        "shop.remove": "(Admin) Remove a shop item by id",
        "settings.menu": "Open an interactive settings menu",
        "settings.currency": "Configure the display name, emoji and balance command name for the currency (UI only)",
        "settings.set_staff_role": "(Owner) Configure the staff role for this server",
        "settings.get_staff_role": "Show the configured staff role for this server",
        "settings.show": "Show key server settings (currency, staff role, mod roles)",
        "settings.mod_role": "(Owner/Admin) Configure which role can use ban/kick/mute",
        "settings.language": "Set the language for command descriptions (en/es)",
        "m.lock": "Lock the current text channel so non-staff cannot send messages",
        "m.unlock": "Unlock the current text channel and restore previous permissions",
        "wheels.create": "Create a wheel post. Users who react with the bot's emoji will join.",
        "wheels.start": "Start the wheel and pick a random winner from reactors",
        "house.create": "Create a House game (creates a private channel).",
        "house.howto": "Quick explanation of how to play Haunted House",
        "house.invite": "Invite a user to your House game (host only).",
        "house.accept": "Accept an invitation to a House game.",
        "house.start": "Start the House game (host only).",
        "house.action": "Perform an action in the House game when it's your turn.",
        "house.move": "Shortcut to move in the current House game (direction: up/down/left/right)",
        "house.explore": "Shortcut to explore the current room in the House game",
        "house.status": "Show game status",
        "house.leave": "Leave a House game",
        "house.end": "End a House game and remove the private channel (host only).",
        "schedule.show": "Show today's schedule (24 slots)",
        "schedule.add": "Add yourself to a numbered slot (1-24)",
        "schedule.delete": "Remove your signup from a numbered slot (1-24)",
    },
    "es": {
        # Top-level
        "wordchain": "Inicia un juego de Cadena de Palabras (únete con botones, empieza cuando estés listo)",
        "ban": "Banea a un usuario por ID. Razón opcional.",
        "kick": "Expulsa a un usuario por ID. Razón opcional.",
        "mute": "Silencia a un usuario por ID durante un tiempo. Razón opcional. Formato: 10m, 2h, 1d",
        "settings_mod": "Configura qué rol puede usar los comandos de moderación (ban/kick/mute). Solo admins/propietario.",
        "snuggles": "Consulta tu saldo de Snuggles",
        "give_snuggles": "(Staff) Da Snuggles a un usuario",
        "rename_currency": "(Staff) Cambia el nombre y/o emoji de la moneda",
        "mm": "Explicación rápida de cómo jugar a 'mm'",
        "setmonopolychannel": "Configura el canal donde se publicarán los enlaces de recompensas de Monopoly GO",
        "unsetmonopolychannel": "Desactiva la publicación automática de enlaces de Monopoly GO en este servidor",
        "custom": "Crea un comando personalizado para este servidor",
        "deletecustom": "Elimina un comando personalizado de este servidor",
        "set_official_links_channel": "Configura el canal donde se publicarán los enlaces oficiales",
        "add_official_link": "Añade un enlace oficial (ej: dado gratis/escudo)",
        "remove_official_link": "Elimina un enlace oficial por su nombre",
        "list_official_links": "Lista los enlaces oficiales guardados para este servidor",
        "post_official_links": "Publica los enlaces oficiales en el canal configurado (o en este canal si no hay configurado)",
        "resync_commands": "Fuerza la re-sincronización de comandos en este servidor (solo administradores)",
        "setmytime": "Guarda tu zona horaria para que /time muestre también tu hora local",
        "settimeformat": "Elige cómo ver la hora: 24h (militar) o 12h (AM/PM)",
        "time": "Muestra la hora actual en cualquier zona horaria o compárala con la de otro usuario",
        # Grupos
        "__shop__": "Comandos de la tienda",
        "__settings__": "Ajustes del servidor",
        "__m__": "Utilidades de moderación",
        "__wheels__": "Crea y ejecuta ruletas de reacción",
        "__house__": "Casa Embrujada: aventuras de texto privadas en solitario o cooperativo",
        "__schedule__": "Ver o añadir inscripciones a horarios",
        # Subcomandos
        "shop.list": "Lista los objetos disponibles en la tienda de este servidor o globales",
        "shop.buy": "Compra un objeto de la tienda usando Snuggles",
        "shop.add": "(Admin) Añade un objeto a la tienda de este servidor o global",
        "shop.remove": "(Admin) Elimina un objeto de la tienda por id",
        "settings.menu": "Abre un menú interactivo de configuración",
        "settings.currency": "Configura el nombre, emoji y comando de saldo de la moneda (solo UI)",
        "settings.set_staff_role": "(Propietario) Configura el rol de staff de este servidor",
        "settings.get_staff_role": "Muestra el rol de staff configurado para este servidor",
        "settings.show": "Muestra los ajustes principales del servidor (moneda, rol staff, roles mod)",
        "settings.mod_role": "(Propietario/Admin) Configura qué rol puede usar ban/kick/mute",
        "settings.language": "Cambia el idioma de las descripciones de los comandos (en/es)",
        "m.lock": "Bloquea el canal de texto actual para que solo el staff pueda enviar mensajes",
        "m.unlock": "Desbloquea el canal de texto actual y restaura los permisos anteriores",
        "wheels.create": "Crea una ruleta. Los usuarios que reaccionen con el emoji del bot entrarán.",
        "wheels.start": "Inicia la ruleta y elige un ganador aleatorio entre los participantes",
        "house.create": "Crea una partida de Casa Embrujada (crea un canal privado).",
        "house.howto": "Explicación rápida de cómo jugar a Casa Embrujada",
        "house.invite": "Invita a un usuario a tu partida de Casa Embrujada (solo el host).",
        "house.accept": "Acepta una invitación a una partida de Casa Embrujada.",
        "house.start": "Inicia la partida de Casa Embrujada (solo el host).",
        "house.action": "Realiza una acción en la partida cuando sea tu turno.",
        "house.move": "Atajo para moverse en la partida (dirección: up/down/left/right)",
        "house.explore": "Atajo para explorar la habitación actual en la partida",
        "house.status": "Muestra el estado de la partida",
        "house.leave": "Abandona una partida de Casa Embrujada",
        "house.end": "Termina la partida y elimina el canal privado (solo el host).",
        "schedule.show": "Muestra el horario de hoy (24 ranuras)",
        "schedule.add": "Añádete a una ranura numerada (1-24)",
        "schedule.delete": "Elimina tu inscripción de una ranura numerada (1-24)",
    },
}


def get_currency_display(guild_id: int | None) -> tuple[str, str]:
    """Return (emoji, name) for currency display.

    This is UI-only: balances remain stored as turkeys in the DB.
    """
    if not guild_id:
        return DEFAULT_CURRENCY_EMOJI, DEFAULT_CURRENCY_NAME
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT currency_display_name, currency_emoji FROM settings WHERE guild_id = %s", (guild_id,))
        row = cur.fetchone()
        conn.close()
        name = (row[0] if row and row[0] else DEFAULT_CURRENCY_NAME)
        emoji = (row[1] if row and row[1] else DEFAULT_CURRENCY_EMOJI)
        return emoji, name
    except Exception:
        return DEFAULT_CURRENCY_EMOJI, DEFAULT_CURRENCY_NAME


def set_currency_display(guild_id: int, name: str | None, emoji: str | None):
    """Set UI-only currency display values for a guild."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings(guild_id, currency_display_name, currency_emoji) VALUES (%s, %s, %s) "
        "ON CONFLICT(guild_id) DO UPDATE SET currency_display_name = %s, currency_emoji = %s",
        (guild_id, name, emoji, name, emoji),
    )
    conn.commit()
    conn.close()


def fmt_currency(guild_id: int | None, amount: int | str) -> str:
    emoji, name = get_currency_display(guild_id)
    # keep name pluralization simple but nice
    try:
        n = int(amount)
        unit = name if n == 1 else f"{name}s"
    except Exception:
        unit = f"{name}s"
    return f"{emoji} {amount} {unit}"


def get_currency_command_name(guild_id: int) -> str:
    """Return the stored slash command name for the balance command (defaults to 'snuggles')."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT currency_command_name FROM settings WHERE guild_id = %s", (guild_id,))
        row = cur.fetchone()
        conn.close()
        return (row[0] if row and row[0] else "snuggles")
    except Exception:
        return "snuggles"


def set_currency_command_name(guild_id: int, cmd_name: str):
    """Persist the slash command name for the balance command for a guild."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings(guild_id, currency_command_name) VALUES (%s, %s) "
        "ON CONFLICT(guild_id) DO UPDATE SET currency_command_name = %s",
        (guild_id, cmd_name, cmd_name),
    )
    conn.commit()
    conn.close()


def get_all_custom_command_names() -> list[tuple[int, str]]:
    """Return [(guild_id, cmd_name), ...] for all guilds with a custom balance command name."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT guild_id, currency_command_name FROM settings WHERE currency_command_name IS NOT NULL")
        rows = cur.fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows if r[1]]
    except Exception:
        return []


def get_guild_language(guild_id: int) -> str:
    """Return the language code for command descriptions for this guild ('en' or 'es'). Defaults to 'en'."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT language FROM settings WHERE guild_id = %s", (guild_id,))
        row = cur.fetchone()
        conn.close()
        return (row[0] if row and row[0] in ("en", "es") else "en")
    except Exception:
        return "en"


def set_guild_language(guild_id: int, lang: str):
    """Persist the language preference for command descriptions for a guild."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings(guild_id, language) VALUES (%s, %s) "
        "ON CONFLICT(guild_id) DO UPDATE SET language = %s",
        (guild_id, lang, lang),
    )
    conn.commit()
    conn.close()


def get_all_guild_languages() -> list[tuple[int, str]]:
    """Return [(guild_id, lang), ...] for guilds with a non-default language set."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT guild_id, language FROM settings WHERE language IS NOT NULL AND language != 'en'")
        rows = cur.fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows if r[1]]
    except Exception:
        return []


def add_turkeys(guild_id: int, user_id: int, amount: int):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO turkeys_balances(guild_id, user_id, turkeys) VALUES (%s, %s, %s) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET turkeys = turkeys_balances.turkeys + %s",
        (guild_id, user_id, amount, amount),
    )
    conn.commit()
    conn.close()

def get_turkeys(guild_id: int, user_id: int) -> int:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT turkeys FROM turkeys_balances WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def set_turkeys(guild_id: int, user_id: int, amount: int):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO turkeys_balances(guild_id, user_id, turkeys) VALUES (%s, %s, %s) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET turkeys = %s",
        (guild_id, user_id, amount, amount),
    )
    conn.commit()
    conn.close()


# Backwards-compatibility wrappers for the old "ghosts" naming. These call the
# new turkey-based functions so external scripts or leftover references keep
# working during the migration.
def add_ghosts(guild_id: int, user_id: int, amount: int):
    return add_turkeys(guild_id, user_id, amount)

def get_ghosts(guild_id: int, user_id: int) -> int:
    return get_turkeys(guild_id, user_id)

def set_ghosts(guild_id: int, user_id: int, amount: int):
    return set_turkeys(guild_id, user_id, amount)


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
    conn = get_db_conn()
    cur = conn.cursor()
    if role_id is None:
        cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (%s, NULL) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = NULL", (guild_id,))
    else:
        cur.execute("INSERT INTO settings(guild_id, staff_role_id) VALUES (%s, %s) ON CONFLICT(guild_id) DO UPDATE SET staff_role_id = %s", (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def get_staff_role(guild_id: int) -> int | None:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT staff_role_id FROM settings WHERE guild_id = %s", (guild_id,))
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
    conn = get_db_conn()
    cur = conn.cursor()
    if role_id is None:
        cur.execute(f"INSERT INTO settings(guild_id, {field}) VALUES (%s, NULL) ON CONFLICT(guild_id) DO UPDATE SET {field} = NULL", (guild_id,))
    else:
        cur.execute(f"INSERT INTO settings(guild_id, {field}) VALUES (%s, %s) ON CONFLICT(guild_id) DO UPDATE SET {field} = %s", (guild_id, role_id, role_id))
    conn.commit()
    conn.close()


def log_moderation(guild_id: int | None, action: str, target_id: int, moderator_id: int, reason: str | None = None):
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO mod_log(guild_id, action, target_id, moderator_id, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (guild_id, action, target_id, moderator_id, reason, datetime.now(timezone.utc).isoformat()))
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
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT {field} FROM settings WHERE guild_id = %s", (guild_id,))
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
        asyncio.create_task(schedule_unmute_check())
    except Exception:
        pass
    # start Monopoly GO auto-poster
    try:
        asyncio.create_task(_monopoly_poster_loop())
    except Exception:
        pass


async def _apply_guild_currency_command(guild_id: int, new_cmd_name: str, old_cmd_name: str | None = None):
    """Register (or rename) a guild-specific slash command for checking the balance.

    The underlying DB uses 'turkeys' — this only affects the Discord command name.
    Pass old_cmd_name to remove the previous command when renaming.
    """
    import re
    clean = new_cmd_name.strip().lower()
    if not re.match(r'^[\w-]{1,32}$', clean):
        raise ValueError(
            f"Invalid command name '{clean}': must be 1–32 chars using only letters, numbers, _ or -."
        )

    guild_obj = discord.Object(id=guild_id)

    # Remove previous custom command if it's different from the new one
    if old_cmd_name and old_cmd_name != clean:
        try:
            bot.tree.remove_command(old_cmd_name, guild=guild_obj)
        except Exception:
            pass

    # Remove any pre-existing command with the target name in this guild (idempotent)
    try:
        bot.tree.remove_command(clean, guild=guild_obj)
    except Exception:
        pass

    # Build the callback — mirrors the global /snuggles command
    async def _balance_callback(interaction: discord.Interaction, user: discord.User | None = None):
        target = user or interaction.user
        gid = getattr(interaction.guild, 'id', 0) or 0
        bal = get_turkeys(gid, target.id)
        await interaction.response.send_message(
            f"{fmt_currency(getattr(interaction.guild, 'id', None), bal)} — {target.mention}",
            ephemeral=True,
        )

    _, cname = get_currency_display(guild_id)
    cmd = app_commands.Command(
        name=clean,
        description=f"Check your {cname} balance",
        callback=_balance_callback,
    )
    bot.tree.add_command(cmd, guild=guild_obj)
    await bot.tree.sync(guild=guild_obj)


# Individual top-level command names managed by _apply_guild_language
_TRANSLATABLE_TOP_LEVEL = [
    "wordchain", "ban", "kick", "mute", "settings_mod",
    "snuggles", "give_snuggles", "rename_currency",
    "mm",
    "setmonopolychannel", "unsetmonopolychannel",
    "custom", "deletecustom",
    "set_official_links_channel", "add_official_link", "remove_official_link",
    "list_official_links", "post_official_links", "resync_commands",
    "setmytime", "time",
]

# Subcommand names per group managed by _apply_guild_language
_TRANSLATABLE_GROUPS: list[tuple[str, str, list[str]]] = [
    ("shop",     "__shop__",     ["list", "buy", "add", "remove"]),
    ("m",        "__m__",        ["lock", "unlock"]),
    ("wheels",   "__wheels__",   ["create", "start"]),
    ("house",    "__house__",    ["create", "howto", "invite", "accept", "start",
                                  "action", "move", "explore", "status", "leave", "end"]),
    ("schedule", "__schedule__", ["show", "add", "delete"]),
    ("settings", "__settings__", ["menu", "currency", "set_staff_role", "get_staff_role",
                                  "show", "mod_role", "language"]),
]


async def _apply_guild_language(guild_id: int, lang: str):
    """Register guild-specific commands with descriptions in the requested language.

    If lang == 'en' (default) and no custom balance command exists, clears guild
    commands and falls back to global (English) ones.
    DB balances are never affected.
    """
    guild_obj = discord.Object(id=guild_id)
    descs = COMMAND_DESCRIPTIONS.get(lang, COMMAND_DESCRIPTIONS["en"])
    custom_cmd = get_currency_command_name(guild_id)

    if lang == "en" and (not custom_cmd or custom_cmd == "snuggles"):
        # Clear guild overrides, fall back to global commands
        try:
            bot.tree.clear_commands(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
        except Exception as _e:
            logging.warning(f"_apply_guild_language clear failed for {guild_id}: {_e}")
        return

    # Clear current guild commands before re-registering with new language
    try:
        bot.tree.clear_commands(guild=guild_obj)
    except Exception:
        pass

    # --- Individual top-level commands ---
    for cmd_name in _TRANSLATABLE_TOP_LEVEL:
        global_cmd = bot.tree.get_command(cmd_name)
        if global_cmd is None:
            continue
        desc = descs.get(cmd_name, global_cmd.description)
        try:
            new_cmd = app_commands.Command(
                name=cmd_name,
                description=desc,
                callback=global_cmd.callback,
            )
            bot.tree.add_command(new_cmd, guild=guild_obj, override=True)
        except Exception:
            pass

    # Custom balance command name (may differ from 'snuggles')
    if custom_cmd and custom_cmd != "snuggles":
        global_snuggles = bot.tree.get_command("snuggles")
        if global_snuggles:
            balance_desc = descs.get("snuggles", global_snuggles.description)
            try:
                extra = app_commands.Command(
                    name=custom_cmd,
                    description=balance_desc,
                    callback=global_snuggles.callback,
                )
                bot.tree.add_command(extra, guild=guild_obj, override=True)
            except Exception:
                pass

    # --- Groups and their subcommands ---
    for group_name, group_key, sub_names in _TRANSLATABLE_GROUPS:
        global_group = bot.tree.get_command(group_name)
        if global_group is None:
            continue
        group_desc = descs.get(group_key, global_group.description)
        new_group = app_commands.Group(name=group_name, description=group_desc)
        for sub_name in sub_names:
            global_sub = global_group.get_command(sub_name)
            if global_sub is None:
                continue
            sub_desc = descs.get(f"{group_name}.{sub_name}", global_sub.description)
            try:
                new_sub = app_commands.Command(
                    name=sub_name,
                    description=sub_desc,
                    callback=global_sub.callback,
                )
                new_group.add_command(new_sub)
            except Exception:
                pass
        try:
            bot.tree.add_command(new_group, guild=guild_obj, override=True)
        except Exception:
            pass

    try:
        await bot.tree.sync(guild=guild_obj)
    except Exception as _e:
        logging.warning(f"_apply_guild_language sync failed for {guild_id}: {_e}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logging.exception(f"Unhandled app command error in '{getattr(interaction.command, 'name', '?')}'", exc_info=error)
    msg = "❌ Se produjo un error inesperado. Inténtalo de nuevo más tarde."
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return  # silently ignore unknown prefix commands
    raise error


@bot.event
async def on_ready():
    """Sync application (slash) commands so `/m lock`, `/m unlock` and `/settings ...` appear.

    If `GUILD_ID` is set, sync only to that guild (fast, dev-friendly).
    Otherwise do a global sync (may take longer to propagate across Discord).
    """
    if getattr(bot, "_did_initial_sync", False):
        return
    bot._did_initial_sync = True

    try:
        logging.info(f"Logged in as {bot.user} (id={getattr(bot.user, 'id', None)})")
    except Exception:
        pass

    # Print a ready-made invite URL if we have the application id
    try:
        if APPLICATION_ID:
            invite = f"https://discord.com/oauth2/authorize?client_id={APPLICATION_ID}&scope=bot%20applications.commands&permissions={BOT_PERMISSIONS}"
            logging.info(f"Invite URL: {invite}")
    except Exception:
        pass

    try:
        if GUILD_ID:
            gid = int(str(GUILD_ID).strip())
            synced = await bot.tree.sync(guild=discord.Object(id=gid))
            logging.info(f"Synced {len(synced)} commands to guild {gid}")
            # Also sync globally so commands appear in DMs
            global_synced = await bot.tree.sync()
            logging.info(f"Synced {len(global_synced)} global commands (for DMs)")
        else:
            synced = await bot.tree.sync()
            logging.info(f"Synced {len(synced)} global commands")
    except Exception:
        logging.exception("Failed to sync application commands")

    # Re-register guild-specific balance commands for guilds with a custom command name
    for _gid, _cmd_name in get_all_custom_command_names():
        try:
            await _apply_guild_currency_command(_gid, _cmd_name)
            logging.info(f"Restored guild balance command '/{_cmd_name}' for guild {_gid}")
        except Exception as _e:
            logging.warning(f"Could not restore guild balance command for {_gid}: {_e}")

    # Restore guild-specific language overrides
    for _gid, _lang in get_all_guild_languages():
        try:
            await _apply_guild_language(_gid, _lang)
            logging.info(f"Restored language '{_lang}' for guild {_gid}")
        except Exception as _e:
            logging.warning(f"Could not restore language for guild {_gid}: {_e}")


async def _gather_original_overwrites(ch: discord.TextChannel) -> dict:
    try:
        return dict(ch.overwrites)
    except Exception:
        # best-effort: try to build from roles that have explicit overwrites
        out = {}
        try:
            # this may raise depending on object shape
            for role in getattr(ch, 'guild', getattr(ch, 'guild', None)).roles:
                try:
                    ow = ch.overwrites_for(role)
                except Exception:
                    ow = None
                if ow is not None:
                    out[role] = ow
        except Exception:
            pass
        return out


async def apply_lock_channel(ch: discord.TextChannel, guild: discord.Guild, staff_role_id: int | None = None):
    """Apply a minimal lock on `ch`: deny @everyone sending, allow staff and bot,
    and deny send for any role that previously had an explicit allow but is not staff/admin.
    Stores original overwrites in `locked_channels` for later restore.
    """
    start = time.time()
    original_overwrites = await _gather_original_overwrites(ch)
    # if already locked, warn (we will overwrite saved state)
    if ch.id in locked_channels:
        logging.warning(f"apply_lock_channel: Channel {ch.id} was already locked; overwriting saved state.")
    locked_channels[ch.id] = original_overwrites

    new_overwrites = dict(original_overwrites)
    # deny @everyone send_messages (preserve view)
    try:
        everyone = guild.default_role
        prev = new_overwrites.get(everyone)
        ow = discord.PermissionOverwrite()
        ow.send_messages = False
        if prev and getattr(prev, 'view_channel', None) is not None:
            ow.view_channel = prev.view_channel
        new_overwrites[everyone] = ow
    except Exception:
        pass

    # allow staff role if provided
    try:
        if staff_role_id:
            staff_role = guild.get_role(staff_role_id)
            if staff_role:
                prev = new_overwrites.get(staff_role)
                ow = discord.PermissionOverwrite()
                ow.send_messages = True
                if prev and getattr(prev, 'view_channel', None) is not None:
                    ow.view_channel = prev.view_channel
                new_overwrites[staff_role] = ow
    except Exception:
        pass

    # ensure bot can still send
    try:
        me = guild.me
        prev = new_overwrites.get(me)
        ow = discord.PermissionOverwrite()
        ow.send_messages = True
        if prev and getattr(prev, 'view_channel', None) is not None:
            ow.view_channel = prev.view_channel
        new_overwrites[me] = ow
    except Exception:
        pass

    # adjust role targets that had explicit allow previously
    # (support both real discord.Role and test fakes)
    try:
        for target, prev_ow in list(original_overwrites.items()):
            is_role_target = isinstance(target, discord.Role) or (
                hasattr(target, 'id') and hasattr(target, 'permissions')
            )
            if is_role_target:
                try:
                    prev_allow = getattr(prev_ow, 'send_messages', None)
                except Exception:
                    prev_allow = None
                if prev_allow:
                    is_staff = False
                    try:
                        if staff_role_id and target.id == staff_role_id:
                            is_staff = True
                        if target.permissions.administrator or target.permissions.manage_guild:
                            is_staff = True
                    except Exception:
                        pass
                    if not is_staff:
                        ow = discord.PermissionOverwrite()
                        ow.send_messages = False
                        try:
                            if getattr(prev_ow, 'view_channel', None) is not None:
                                ow.view_channel = prev_ow.view_channel
                        except Exception:
                            pass
                        new_overwrites[target] = ow
    except Exception:
        pass

    fallback_used = False
    per_target_success = 0
    per_target_fail = 0
    async with permission_op_lock:
        try:
            await ch.edit(overwrites=new_overwrites)
        except Exception as e:
            fallback_used = True
            logging.warning(f"apply_lock_channel: ch.edit failed for channel {ch.id}: {e}. Falling back to per-target set_permissions.")
            for target, ow in new_overwrites.items():
                try:
                    await ch.set_permissions(target, overwrite=ow)
                    per_target_success += 1
                except Exception:
                    per_target_fail += 1
                    pass
    elapsed = time.time() - start
    if fallback_used:
        logging.info(f"apply_lock_channel: Channel {ch.id} locked in {elapsed:.3f}s (fallback used). Per-target successes={per_target_success} failures={per_target_fail}")
    else:
        logging.info(f"apply_lock_channel: Channel {ch.id} locked in {elapsed:.3f}s (single edit).")


async def apply_unlock_channel(ch: discord.TextChannel):
    """Restore overwrites previously saved by apply_lock_channel."""
    start = time.time()
    prev = locked_channels.get(ch.id)
    if not prev:
        raise RuntimeError("No locked state saved for channel")
    fallback_used = False
    per_target_success = 0
    per_target_fail = 0
    async with permission_op_lock:
        try:
            await ch.edit(overwrites=prev)
        except Exception as e:
            fallback_used = True
            logging.warning(f"apply_unlock_channel: ch.edit failed for channel {ch.id}: {e}. Falling back to per-target restore.")
            for target, ow in prev.items():
                try:
                    await ch.set_permissions(target, overwrite=ow)
                    per_target_success += 1
                except Exception:
                    per_target_fail += 1
                    pass
    elapsed = time.time() - start
    if fallback_used:
        logging.info(f"apply_unlock_channel: Channel {ch.id} unlocked in {elapsed:.3f}s (fallback used). Per-target successes={per_target_success} failures={per_target_fail}")
    else:
        logging.info(f"apply_unlock_channel: Channel {ch.id} unlocked in {elapsed:.3f}s (single edit).")
    try:
        del locked_channels[ch.id]
    except KeyError:
        pass



@bot.event
async def on_message(message: discord.Message):
    """Handle simple message-based moderation commands.

    Supported forms:
    - `/m lock` / `/m unlock`

    `lock` will prevent non-staff roles from sending messages in the channel
    while keeping view permissions unchanged. `unlock` restores previous
    send_messages overwrites saved when locking.
    """
    # ignore bots
    if message.author.bot:
        return

    content = (message.content or "").strip()

    # Handle custom commands (invoked with the ! prefix)
    if content.startswith('!') and message.guild:
        raw = content[1:].split()[0].lower() if content[1:].strip() else ''
        if raw:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT info FROM custom_commands WHERE guild_id = %s AND name = %s",
                (message.guild.id, raw)
            )
            row = cur.fetchone()
            conn.close()
            if row:
                await message.channel.send(row[0])
                return

    cmd = ''
    parts = content.split()

    if len(parts) >= 2:
        first = parts[0].lower()
        # Allow sending as a literal message by escaping the slash: `\/m lock`
        if first.startswith('\\'):
            first = first[1:]
        if first == '/m':
            cmd = parts[1].lower()
    else:
        # let other command processors handle it
        await bot.process_commands(message)
        return

    if cmd not in ('lock', 'unlock'):
        await bot.process_commands(message)
        return

    # must be used in a guild text channel
    if not message.guild or not isinstance(message.channel, discord.TextChannel):
        try:
            await message.channel.send("This command must be used in a server text channel.")
        except Exception:
            pass
        return

    # permission check: only staff may run lock/unlock
    try:
        allowed = await is_staff_in_guild(message.guild, message.author.id)
    except Exception:
        allowed = False
    if not allowed:
        try:
            await message.channel.send("You do not have permission to use this command.")
        except Exception:
            pass
        return

    ch: discord.TextChannel = message.channel
    guild = message.guild

    if cmd == 'lock':
        logging.info(f"Lock command invoked by {message.author} in {ch.id}")
        # Save the full existing overwrites so we can restore them later
        try:
            original_overwrites = dict(ch.overwrites)
        except Exception:
            original_overwrites = {}

        # Store original overwrites in-memory so unlock can restore them
        if ch.id in locked_channels:
            logging.warning(f"on_message .lock: Channel {ch.id} already locked; overwriting saved state.")
        locked_channels[ch.id] = original_overwrites

        # Strategy: minimize changed targets. Deny @everyone send_messages and
        # explicitly allow staff and bot. Also, for any role that currently has
        # an explicit overwrite allowing send_messages and is not staff/admin,
        # flip it to deny so non-staff can't send.
        new_overwrites = dict(original_overwrites)  # start from original
        staff_role_id = get_staff_role(guild.id)

        # Ensure @everyone is denied send_messages (preserve view_channel)
        try:
            everyone = guild.default_role
            prev = new_overwrites.get(everyone)
            ow = discord.PermissionOverwrite()
            ow.send_messages = False
            if prev and getattr(prev, 'view_channel', None) is not None:
                ow.view_channel = prev.view_channel
            new_overwrites[everyone] = ow
        except Exception:
            pass

        # Ensure staff role (if configured) can send
        try:
            if staff_role_id:
                staff_role = guild.get_role(staff_role_id)
                if staff_role:
                    prev = new_overwrites.get(staff_role)
                    ow = discord.PermissionOverwrite()
                    ow.send_messages = True
                    if prev and getattr(prev, 'view_channel', None) is not None:
                        ow.view_channel = prev.view_channel
                    new_overwrites[staff_role] = ow
        except Exception:
            pass

        # Ensure bot can still send
        try:
            me = guild.me
            prev = new_overwrites.get(me)
            ow = discord.PermissionOverwrite()
            ow.send_messages = True
            if prev and getattr(prev, 'view_channel', None) is not None:
                ow.view_channel = prev.view_channel
            new_overwrites[me] = ow
        except Exception:
            pass

        # For any role that had explicit allow send_messages and is not staff/admin,
        # set send_messages=False to prevent bypass.
        try:
            for target, prev_ow in list(original_overwrites.items()):
                if isinstance(target, discord.Role):
                    try:
                        prev_allow = getattr(prev_ow, 'send_messages', None)
                    except Exception:
                        prev_allow = None
                    if prev_allow:
                        # check staff/admin
                        is_staff = False
                        try:
                            if staff_role_id and target.id == staff_role_id:
                                is_staff = True
                            if target.permissions.administrator or target.permissions.manage_guild:
                                is_staff = True
                        except Exception:
                            pass
                        if not is_staff:
                            # change to deny send_messages but preserve view_channel
                            ow = discord.PermissionOverwrite()
                            ow.send_messages = False
                            try:
                                if getattr(prev_ow, 'view_channel', None) is not None:
                                    ow.view_channel = prev_ow.view_channel
                            except Exception:
                                pass
                            new_overwrites[target] = ow
        except Exception:
            pass

        # Apply in a single edit under the permission_op_lock for safety
        start = time.time()
        fallback_used = False
        per_target_success = 0
        per_target_fail = 0
        async with permission_op_lock:
            try:
                await ch.edit(overwrites=new_overwrites)
                logging.info(f"Channel {ch.id} locked (minimal changes).")
            except Exception as e:
                fallback_used = True
                logging.warning(f"ch.edit failed during optimized lock in channel {ch.id}: {e}. Falling back to per-target set_permissions.")
                for target, ow in new_overwrites.items():
                    try:
                        await ch.set_permissions(target, overwrite=ow)
                        per_target_success += 1
                    except Exception:
                        per_target_fail += 1
                        pass
        elapsed = time.time() - start
        if fallback_used:
            logging.info(f"on_message .lock: Channel {ch.id} locked in {elapsed:.3f}s (fallback used). Per-target successes={per_target_success} failures={per_target_fail}")
        else:
            logging.info(f"on_message .lock: Channel {ch.id} locked in {elapsed:.3f}s (single edit).")

        try:
            await ch.send("Channel locked: only staff can send messages. Viewing permissions were not changed.")
        except Exception:
            pass
        return

    if cmd == 'unlock':
        prev = locked_channels.get(ch.id)
        if not prev:
            try:
                await ch.send("Channel is not locked by me or no previous state saved.")
            except Exception:
                pass
            return

        # Restore the original overwrites in a single edit call
        start = time.time()
        fallback_used = False
        per_target_success = 0
        per_target_fail = 0
        async with permission_op_lock:
            try:
                await ch.edit(overwrites=prev)
                elapsed = time.time() - start
                logging.info(f"Channel {ch.id} unlocked with {len(prev)} overwrites restored (single edit) in {elapsed:.3f}s.")
            except Exception as e:
                fallback_used = True
                logging.warning(f"ch.edit failed during unlock in channel {ch.id}: {e}. Falling back to per-target restore.")
                for target, ow in prev.items():
                    try:
                        await ch.set_permissions(target, overwrite=ow)
                        per_target_success += 1
                    except Exception:
                        per_target_fail += 1
                        pass
                elapsed = time.time() - start
                logging.info(f"on_message .unlock: Channel {ch.id} unlocked in {elapsed:.3f}s (fallback used). Per-target successes={per_target_success} failures={per_target_fail}")

        try:
            del locked_channels[ch.id]
        except KeyError:
            pass
        try:
            await ch.send("Channel unlocked and previous send permissions restored.")
        except Exception:
            pass
        return


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
                    # apply channel overwrites in background with delays to avoid rate limits
                    async def _apply_muted_overwrites():
                        for ch in interaction.guild.channels:
                            try:
                                await ch.set_permissions(muted_role, send_messages=False, speak=False)
                            except Exception:
                                pass
                            await asyncio.sleep(0.25)

                    try:
                        asyncio.create_task(run_coro_safe(_apply_muted_overwrites(), name=f"apply-muted-{interaction.guild.id}"))
                    except Exception:
                        # best-effort synchronous fallback (may hit rate limits)
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
    conn = get_db_conn()
    cur = conn.cursor()
    if guild_id:
        cur.execute("SELECT id, name, price, role_id FROM shop_items WHERE guild_id = %s", (guild_id,))
    else:
        cur.execute("SELECT id, name, price, role_id FROM shop_items WHERE guild_id IS NULL")
    rows = cur.fetchall()
    conn.close()
    return rows

def add_shop_item(name: str, price: int, guild_id: int | None = None, role_id: int | None = None, metadata: str | None = None):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO shop_items(guild_id, name, price, role_id, metadata) VALUES (%s, %s, %s, %s, %s)", (guild_id, name, price, role_id, metadata))
    conn.commit()
    conn.close()

def remove_shop_item(item_id: int):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM shop_items WHERE id = %s", (item_id,))
    conn.commit()
    conn.close()

def get_shop_item(item_id: int):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, guild_id, name, price, role_id, metadata FROM shop_items WHERE id = %s", (item_id,))
    row = cur.fetchone()
    conn.close()
    return row

def maybe_halloween_announce(channel: discord.abc.GuildChannel):
    today = date.today()
    if today.month == 10 and 25 <= today.day <= 31:
        if random.random() < 0.25:
            try:
                emoji, name = get_currency_display(getattr(channel, 'guild', None).id if getattr(channel, 'guild', None) else None)
                asyncio.create_task(run_coro_safe(channel.send(f"Halloween event active! In this game the winner will receive {emoji} {name}."), name=f"halloween-announce-{getattr(channel, 'id', 'chan')}"))
            except Exception:
                pass

# Furby tournament removed.
# The TournamentView implementation (Furby) was deleted to remove the /furbytournament game.
# --- Teddy War: messages, view and command ---
TEDDY_MESSAGE_GROUPS = {
    "pillow": {
        "attacks": [
            "{a} smacks {d} with a gigantic fluffy pillow — sweet dreams!",
            "{a} launches a surprise pillow bomb at {d}. Feathers everywhere!",
            "{a} sneaks a tickle attack; {d} collapses laughing.",
            "{a} performs the Pillow Tsunami — {d} is carried away.",
        ],
        "kills": [
            "{a} pillows {d} into a permanent nap. Zzzz...",
            "{d} was fluffed to oblivion by {a}. No waking up today.",
            "A mountain of cushions buries {d} — note: no more waking.",
            "{d} choked on a rogue pom-pom and went into sleep mode.",
            "Overstuffed! {d}'s seams burst and he drifts off forever.",
        ],
        "revives": [
            "{d} sneezes out a battery and bounces back!",
            "A stray pillow springs {d} back to life — recharge complete!",
            "Someone finds a spare stitch and sews {d} back together.",
        ],
        "taunts": [
            "{a} strikes a victory pose while feathers rain down on {d}.",
            "{a} ruffles {d}'s stuffing and laughs maniacally.",
            "{a} whispers 'nap time' as feathers float by.",
        ],
    },
    "sword": {
        "attacks": [
            "{a} brandishes a foam sword and taps {d} — honorably incapacitated.",
            "{a} performs the legendary 'Cuddly Slash' and {d} topples.",
            "{a} pokes {d} with a plastic sword; dramatic fall follows.",
            "{a} trips and accidentally flips {d} into next Tuesday.",
        ],
        "kills": [
            "{a} disarms {d} with a dramatic squeak — {d} falls dramatically.",
            "{d} is skewered by a glue-stick lance and exits stage left.",
            "{d} slips on a toy car and the sword delivers a final poke.",
            "{d} gets tangled in a scarf and is theatrically removed from the play.",
        ],
        "revives": [
            "{d} patches up their plush seams and returns, fiercer than ever!",
            "{d} discovers a hidden button labeled 'Restart' and pops back in.",
            "A meddling sibling presses 'Undo' and {d} reappears, intact.",
        ],
        "taunts": [
            "{a} polishes their tiny sword and winks at {d}.",
            "{a} whispers 'I hug, therefore I win' to {d}.",
            "{a} does a tiny bow while {d} coughs stuffing.",
        ],
    },
    "epic": {
        "attacks": [
            "{a} leaps through a storm of fluff and lands a thunderous hug on {d}.",
            "{a} swings their glitter blade; {d} is stunned by the sparkle.",
            "{a} summons a confetti comet that bonks {d} on the head.",
            "{a} fires a glitter blast — {d} is dazzled and collapses.",
        ],
        "kills": [
            "{d} is knocked into the pillow void — no return ticket.",
            "{a} delivers the 'Cuddle Overload' — system shutdown for {d}.",
            "The spotlight hits {d} as they take their final curtain nap.",
            "{d} is slowly un-stuffed by the sparkle vortex and drifts away.",
        ],
        "revives": [
            "{d} miraculously regains fluff after applause from an invisible audience.",
            "A tiny fairy teddy tosses a stitch and {d} wakes up again.",
            "A fan club chants until {d} pops back into existence.",
        ],
        "taunts": [
            "{a} does a slow clap with adorable paw gestures.",
            "{a} juggles feathers while {d} coughs fluff.",
            "{a} tosses a glitter coin and winks at {d}.",
        ],
    },
    "hero": {
        "attacks": [
            "{a} stares down {d} with heroic eyes and gives a noble poke.",
            "{a} charges bravely, wielding a sword twice their size.",
            "{a} offers a sacrificial hug that knocks {d} out of the ring.",
        ],
        "kills": [
            "{a} slays the shadow with a single squeak — legend born.",
            "{d} fades into bedtime stories after that heroic slap.",
            "{d} is retired to the Hall of Tiny Heroes (rest in softness).",
        ],
        "revives": [
            "{d} finds hidden courage stuffed in their belly and stands up again.",
            "{d} drinks a cup of tiny tea and is back for round two.",
            "A heroic tale rewrites the outcome and {d} returns triumphant.",
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
            "{a} attempts the risky 'Paw Jab' and the room shudders.",
        ],
        "kills": [
            "{a} barely survives; {d} is swallowed by the boss's scary fluff.",
            "{d} gets squashed under a giant paw and disappears.",
            "{d} is sent to the Lost Toy Bin — never to be seen again.",
            "{d} is taken out by a thunderous snore from the boss.",
        ],
        "revives": [
            "{d} coughs up a spare pom-pom and returns to the fray!",
            "The crowd chants and {d} rematerializes, slightly singed but ready.",
            "A last-minute alliance stitches {d} back together.",
        ],
        "taunts": [
            "{a} growls like a 2-inch warrior and it somehow works.",
            "{a} polishes their sword while the boss frowns.",
        ],
    },
}

# Map specific filenames to groups so texts match image themes
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


def _pick_non_repeating_image(candidate_paths, last_image: str | None = None):
    """Pick an image path from candidate_paths avoiding `last_image` when possible.
    `candidate_paths` is an iterable of paths (may include None). Returns a valid
    existing path or None if none found.
    """
    # Filter to existing files
    candidates = [p for p in candidate_paths if p and os.path.isfile(p)]
    # prefer a candidate different from last_image
    for p in candidates:
        if p != last_image:
            return p
    # fallback: pick a random teddy asset that's different from last_image
    assets = load_teddy_images()
    assets = [a for a in assets if a and a != last_image and os.path.isfile(a)]
    if assets:
        return random.choice(assets)
    # give up: return first candidate or None
    return candidates[0] if candidates else None

class TeddyTournamentView(discord.ui.View):
    def __init__(self, host: discord.Member | None = None, timeout: int | None = None):
        super().__init__(timeout=timeout)
        self.host = host

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="Join Tournament", style=discord.ButtonStyle.success, emoji="🧸")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_message("You have joined the teddy war.", ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send("You have joined the teddy war.", ephemeral=True)
            except Exception:
                pass
        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        meta = tournaments_meta.get(msg_id, {})
        maxp = meta.get("max_participants", 50)
        if interaction.user.id in participants:
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
        preview = "\n".join([f"<@{uid}>" for uid in list(participants)[:20]])
        try:
            await safe_reply(interaction, f"{interaction.user.mention} just joined the teddy war.\nParticipants: {len(participants)}/{maxp}\n\n{preview}")
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
        try:
            await interaction.response.send_message("Teddy war starting! 🔥", ephemeral=False)
        except Exception:
            try:
                await interaction.followup.send("Teddy war starting! 🔥", ephemeral=False)
            except Exception:
                pass
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
        import random
        channel = interaction.channel
        try:
            await interaction.response.send_message("The teddy war battle begins! 🔥", ephemeral=False)
        except Exception:
            pass
        alive = list(participants)
        eliminated = []
        revived_once = set()
        meta = tournaments_meta.get(msg_id, {})
        max_revives = max(1, len(alive) // 10)
        revives_used = 0
        # Ensure teddy images (consistent per participant)
        image_map = ensure_teddy_images(msg_id, alive)
        last_posted_image = None
        while len(alive) > 1:
            a, d = random.sample(alive, 2)
            attacker_img = image_map.get(a)
            defender_img = image_map.get(d)
            msgs = _get_teddy_messages_for_image(attacker_img) or TEDDY_MESSAGE_GROUPS["sword"]
            attack_msg = random.choice(msgs["attacks"]).format(a=f"<@{a}>", d=f"<@{d}>")

            # Choose an image to post for this attack, avoiding the last posted image
            post_img = _pick_non_repeating_image([attacker_img, defender_img], last_posted_image)
            try:
                if post_img:
                    embed_msg = discord.Embed(description=attack_msg)
                    try:
                        file = discord.File(post_img)
                        embed_msg.set_image(url=f"attachment://{os.path.basename(post_img)}")
                        await channel.send(embed=embed_msg, file=file)
                    except Exception:
                        await channel.send(attack_msg)
                else:
                    await channel.send(attack_msg)
            except discord.Forbidden:
                print(f"Warning: cannot send battle message in channel {getattr(channel, 'id', None)} - missing permissions.")
            except discord.HTTPException as e:
                print(f"Warning: failed to send battle message: {e}")

            last_posted_image = post_img
            await asyncio.sleep(random.uniform(3, 7))

            killer, victim = (a, d) if random.random() < 0.6 else (d, a)
            if victim in alive:
                alive.remove(victim)
                eliminated.append(victim)

            # Kill message
            msgs_k = _get_teddy_messages_for_image(image_map.get(killer)) or TEDDY_MESSAGE_GROUPS["sword"]
            kill_text = random.choice(msgs_k["kills"]).format(a=f"<@{killer}>", d=f"<@{victim}>")
            # Prefer killer image, but avoid repeating last image
            post_img = _pick_non_repeating_image([image_map.get(killer), image_map.get(victim)], last_posted_image)
            try:
                if post_img:
                    embed_kill = discord.Embed(description=kill_text)
                    try:
                        file = discord.File(post_img)
                        embed_kill.set_image(url=f"attachment://{os.path.basename(post_img)}")
                        await channel.send(embed=embed_kill, file=file)
                    except Exception:
                        await channel.send(kill_text)
                else:
                    await channel.send(kill_text)
            except discord.Forbidden:
                print(f"Warning: cannot send kill message in channel {getattr(channel, 'id', None)} - missing permissions.")
            except discord.HTTPException as e:
                print(f"Warning: failed to send kill message: {e}")

            last_posted_image = post_img

            # revive chance
            if revives_used < max_revives and victim not in revived_once and random.random() < 0.5:
                revived_once.add(victim)
                revives_used += 1
                alive.append(victim)
                rev_msgs = _get_teddy_messages_for_image(image_map.get(victim)) or TEDDY_MESSAGE_GROUPS["sword"]
                rev_msg = random.choice(rev_msgs["revives"]).format(d=f"<@{victim}>")

                balive_imgs = get_special_teddy_images("balive")
                rev_candidates = balive_imgs if balive_imgs else [image_map.get(victim)]
                post_img = _pick_non_repeating_image(rev_candidates, last_posted_image)
                try:
                    if post_img:
                        embed_rev = discord.Embed(description=rev_msg)
                        try:
                            file = discord.File(post_img)
                            embed_rev.set_image(url=f"attachment://{os.path.basename(post_img)}")
                            await channel.send(embed=embed_rev, file=file)
                        except Exception:
                            await channel.send(rev_msg)
                    else:
                        await channel.send(rev_msg)
                except discord.Forbidden:
                    print(f"Warning: cannot send revive message in channel {getattr(channel, 'id', None)} - missing permissions.")
                except discord.HTTPException as e:
                    print(f"Warning: failed to send revive message: {e}")

                last_posted_image = post_img
            else:
                if random.random() < 0.3:
                    try:
                        taunts = _get_teddy_messages_for_image(image_map.get(killer)) or TEDDY_MESSAGE_GROUPS["sword"]
                        taunt_text = random.choice(taunts["taunts"]).format(a=f"<@{killer}>", d=f"<@{victim}>")
                        # try to attach a non-repeating image for the taunt too
                        taunt_img = _pick_non_repeating_image([image_map.get(killer)], last_posted_image)
                        if taunt_img:
                            embed_t = discord.Embed(description=taunt_text)
                            try:
                                file = discord.File(taunt_img)
                                embed_t.set_image(url=f"attachment://{os.path.basename(taunt_img)}")
                                await channel.send(embed=embed_t, file=file)
                            except Exception:
                                await channel.send(taunt_text)
                            last_posted_image = taunt_img
                        else:
                            await channel.send(taunt_text)
                    except Exception:
                        pass
            await asyncio.sleep(random.uniform(3, 7))
        # Winner
        winner_id = alive[0]
        guild = interaction.guild
        # Save stats (reuse existing wins tables)
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO wins_global(user_id, wins) VALUES (%s, 1) ON CONFLICT(user_id) DO UPDATE SET wins = wins_global.wins + 1", (winner_id,))
        if guild:
            cur.execute("INSERT INTO wins_guild(guild_id, user_id, wins) VALUES (%s, %s, 1) ON CONFLICT(guild_id, user_id) DO UPDATE SET wins = wins_guild.wins + 1", (guild.id, winner_id))
        conn.commit()
        cur.execute("SELECT wins FROM wins_global WHERE user_id = %s", (winner_id,))
        global_wins = cur.fetchone()[0]
        guild_wins = 0
        if guild:
            cur.execute("SELECT wins FROM wins_guild WHERE guild_id = %s AND user_id = %s", (guild.id, winner_id))
            row = cur.fetchone()
            guild_wins = row[0] if row else 0
        conn.close()
        meta = tournaments_meta.get(msg_id, {})
        start_ts = meta.get("start")
        duration_text = "unknown"
        if start_ts:
            dur = int(time.time() - start_ts)
            mins, secs = divmod(dur, 60)
            duration_text = f"{mins}m {secs}s"
        winner_mention = f"<@{winner_id}>"
        host_mention = f"<@{self.host.id}>" if self.host else "(unknown)"
        winner_text = f"Now war ended and {winner_mention} is the last survivor  {winner_mention} is going to sleep, dinner dinner sleppy before dinner"
        winner_imgs = get_special_teddy_images("winner")
        winner_img = _pick_non_repeating_image(winner_imgs, last_posted_image) if winner_imgs else None
        try:
            if winner_img:
                embed_w = discord.Embed(description=winner_text)
                try:
                    file = discord.File(winner_img)
                    embed_w.set_image(url=f"attachment://{os.path.basename(winner_img)}")
                    await channel.send(embed=embed_w, file=file)
                except Exception:
                    await channel.send(winner_text)
            else:
                await channel.send(winner_text)
        except Exception:
            pass
        # Award turkeys/snuggles similar to furby
        try:
            participants_total = len(participants)
            turkeys_awarded = 2 * participants_total
            try:
                if await is_staff_in_guild(interaction.guild, winner_id):
                    try:
                        _emoji, _cname = get_currency_display(getattr(interaction.guild, 'id', None))
                        await channel.send(f"{_emoji} {winner_mention} is staff and has unlimited {_cname} — congratulations!")
                    except Exception:
                        pass
                else:
                    add_turkeys(getattr(interaction.guild, 'id', 0) or 0, winner_id, turkeys_awarded)
                    try:
                        await channel.send(f"{fmt_currency(getattr(interaction.guild, 'id', None), turkeys_awarded)} have been awarded to {winner_mention}!")
                    except Exception:
                        pass
            except Exception:
                try:
                    add_turkeys(getattr(interaction.guild, 'id', 0) or 0, winner_id, turkeys_awarded)
                except Exception:
                    pass
        except Exception:
            pass
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Cancel Tournament", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

# Slash command to create teddy war
@bot.tree.command(name="teddy_war", description="Create a Teddy War tournament embed")
@app_commands.describe(title="Title for the tournament")
async def teddy_war(interaction: discord.Interaction, title: str = "Teddy War"):
    host = interaction.user
    embed = discord.Embed(title=title, color=0xFF69B4)
    description = (
        "Tournament ID: teddy-" + str(int(time.time())) + "\n\n"
        "Instructions:\n"
        "• Click Join Tournament to enter your Teddy\n"
        "• The host can start the war when ready\n"
        "• Maximum 50 participants allowed\n\n"
        "Have fun and be silly! Your Teddy's image will be shown during battles."
    )
    embed.description = description
    embed.set_footer(text=f"Host: {host.display_name}")
    view = TeddyTournamentView(host=host, timeout=None)
    msg = await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
    sent = await interaction.original_response()
    tournaments[sent.id] = set()
    tournaments_meta[sent.id] = {
        "host": host.id,
        "start": int(time.time()),
        "max_participants": 50,
    }


# ---------------- Slash commands: Snuggles balance & shop ----------------
@bot.tree.command(name="snuggles", description="Check your Snuggles balance")
@app_commands.describe(user="User to check (optional)")
async def turkeys_balance(interaction: discord.Interaction, user: discord.User | None = None):
    target = user or interaction.user
    gid = getattr(interaction.guild, 'id', 0) or 0
    bal = get_turkeys(gid, target.id)
    await interaction.response.send_message(f"{fmt_currency(getattr(interaction.guild, 'id', None), bal)} — {target.mention}", ephemeral=True)


@bot.tree.command(name="give_snuggles", description="(Staff) Give Snuggles to a user")
@app_commands.describe(target="Target user", amount="Amount of Snuggles to give (can be negative)")
async def give_turkeys(interaction: discord.Interaction, target: discord.User, amount: int):
    # Only members with the configured staff role (or fallback perms) can use this
    try:
        guild = interaction.guild
        if not guild:
            await safe_reply(interaction, "This command must be used in a server.")
            return
        # check configured staff role or fallback permissions
        if not await is_staff_in_guild(guild, interaction.user.id):
            emoji, name = get_currency_display(guild.id)
            await safe_reply(interaction, f"You are not authorized to give {emoji} {name}. Staff only.")
            return

        # proceed to give turkeys
        add_turkeys(guild.id, target.id, amount)
        bal = get_turkeys(guild.id, target.id)
        await safe_reply(interaction, f"{fmt_currency(guild.id, amount)} given to {target.mention}. New balance: {fmt_currency(guild.id, bal)}")
    except Exception as e:
        await safe_reply(interaction, f"Error giving Snuggles: {e}")


@bot.tree.command(name="rename_currency", description="(Staff) Change the display name and/or emoji of the currency")
@app_commands.describe(
    name="New display name (e.g. Snuggles). Use '-' to reset to default.",
    emoji="New emoji (e.g. 🦃). Use '-' to reset to default.",
)
async def rename_currency(interaction: discord.Interaction, name: str | None = None, emoji: str | None = None):
    if not interaction.guild:
        await safe_reply(interaction, "This command must be used in a server.")
        return
    if not await is_staff_in_guild(interaction.guild, interaction.user.id):
        await safe_reply(interaction, "Only staff can rename the currency.")
        return
    if name is None and emoji is None:
        e, n = get_currency_display(interaction.guild.id)
        await safe_reply(interaction, f"Current currency display: {e} {n}\nUse `/rename_currency name:<name> emoji:<emoji>` to change it.", ephemeral=True)
        return
    if name == '-':
        name = None
    if emoji == '-':
        emoji = None
    cur_emoji, cur_name = get_currency_display(interaction.guild.id)
    new_name = (name.strip() or cur_name) if name is not None else cur_name
    new_emoji = (emoji.strip() or cur_emoji) if emoji is not None else cur_emoji
    set_currency_display(interaction.guild.id, new_name, new_emoji)
    await safe_reply(interaction, f"Currency renamed to: {new_emoji} {new_name}\n*(Display only — balances in the DB are unchanged.)*", ephemeral=True)


shop_group = app_commands.Group(name="shop", description="Shop commands")
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
        lines.append(f"{item_id}: {name} — {fmt_currency(gid, price)}{role_part}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@shop_group.command(name="buy", description="Buy a shop item using Snuggles")
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
    gid = getattr(interaction.guild, 'id', 0) or 0
    bal = get_turkeys(gid, user_id)
    if bal < price:
        emoji, cname = get_currency_display(getattr(interaction.guild, 'id', None))
        await interaction.response.send_message(
            f"You don't have enough {emoji} {cname}. You have {fmt_currency(getattr(interaction.guild, 'id', None), bal)}, but the item costs {fmt_currency(getattr(interaction.guild, 'id', None), price)}.",
            ephemeral=True,
        )
        return
    # deduct
    add_turkeys(gid, user_id, -price)
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
    await interaction.response.send_message(f"You bought **{name}** for {fmt_currency(getattr(interaction.guild, 'id', None), price)}.", ephemeral=True)


@shop_group.command(name="add", description="(Admin) Add a shop item to this server or global")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(name="Item name", price="Price in Snuggles", role="Optional role to grant")
async def shop_add(interaction: discord.Interaction, name: str, price: int, role: discord.Role | None = None, global_item: bool = False):
    gid = None if global_item else (interaction.guild.id if interaction.guild else None)
    role_id = role.id if role else None
    add_shop_item(name=name, price=price, guild_id=gid, role_id=role_id)
    await interaction.response.send_message(f"Added shop item: {name} — {fmt_currency(gid, price)}", ephemeral=True)


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


class CurrencySettingsModal(discord.ui.Modal, title="Configurar moneda"):
    def __init__(self):
        super().__init__(timeout=180)
        self.currency_name = discord.ui.TextInput(
            label="Nombre de la moneda",
            required=False,
            max_length=32,
            placeholder="Ej: Snuggles",
        )
        self.currency_emoji = discord.ui.TextInput(
            label="Emoji (unicode o <:nombre:id> del servidor)",
            required=False,
            max_length=64,
            placeholder="Ej: 🦃 o <:furby:123456789>",
        )
        self.cmd_name = discord.ui.TextInput(
            label="Nombre del comando /balance (letras, números, _)",
            required=False,
            max_length=32,
            placeholder="Ej: snuggles  (deja vacío para no cambiar)",
        )
        self.add_item(self.currency_name)
        self.add_item(self.currency_emoji)
        self.add_item(self.cmd_name)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            await safe_reply(interaction, "Este comando debe usarse en un servidor.")
            return

        # Permisos: similar a @has_permissions(manage_guild=True) pero con mensaje claro.
        try:
            member = interaction.guild.get_member(interaction.user.id) or await interaction.guild.fetch_member(interaction.user.id)
            perms = member.guild_permissions
            if not (perms.manage_guild or perms.administrator):
                await safe_reply(interaction, "Necesitas el permiso **Manage Server** para cambiar la moneda.")
                return
        except Exception:
            await safe_reply(interaction, "No pude comprobar tus permisos.")
            return

        name = (str(self.currency_name.value).strip() if self.currency_name.value is not None else "")
        emoji = (str(self.currency_emoji.value).strip() if self.currency_emoji.value is not None else "")
        cmd = (str(self.cmd_name.value).strip().lower() if self.cmd_name.value else "")

        # Si no pone nada, mostramos el estado actual
        if not name and not emoji and not cmd:
            e, n = get_currency_display(interaction.guild.id)
            cur_cmd = get_currency_command_name(interaction.guild.id)
            await safe_reply(interaction, f"Moneda actual: {e} {n}  |  Comando: `/{cur_cmd}` (solo UI)")
            return

        # Permitir reset con '-'
        if name == '-':
            name = ""
        if emoji == '-':
            emoji = ""
        if cmd == '-':
            cmd = ""

        try:
            cur_emoji, cur_name = get_currency_display(interaction.guild.id)
            new_name = cur_name if name == "" else name
            new_emoji = cur_emoji if emoji == "" else emoji
            set_currency_display(interaction.guild.id, new_name, new_emoji)

            # Registrar nuevo comando de guild si se especificó
            cmd_info = ""
            if cmd:
                import re as _re
                if not _re.match(r'^[\w-]{1,32}$', cmd):
                    await safe_reply(interaction, f"Nombre de comando inválido `{cmd}`: solo letras, números, _ o - (1-32 caracteres).")
                    return
                old_cmd = get_currency_command_name(interaction.guild.id)
                set_currency_command_name(interaction.guild.id, cmd)
                try:
                    await _apply_guild_currency_command(interaction.guild.id, cmd, old_cmd if old_cmd != cmd else None)
                    cmd_info = f"  |  Comando renombrado a `/{cmd}`"
                except Exception as ce:
                    cmd_info = f"  |  ⚠️ Error al registrar el comando: {ce}"

            await safe_reply(interaction, f"Moneda actualizada: {new_emoji} {new_name} (solo UI){cmd_info}")
        except Exception as e:
            await safe_reply(interaction, f"No se pudo actualizar la moneda: {e}")


class SettingsMenuView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await safe_reply(interaction, "Solo la persona que abrió este menú puede usarlo.")
            return False
        if not interaction.guild:
            await safe_reply(interaction, "Este menú solo funciona en un servidor.")
            return False
        return True

    @discord.ui.select(
        placeholder="¿Qué quieres configurar?",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="Moneda (Snuggles)",
                value="currency",
                description="Cambiar nombre y emoji (solo UI)",
                emoji=TURKEY_EMOJI,
            ),
        ],
    )
    async def select_settings(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await self._guard(interaction):
            return
        choice = (select.values[0] if select.values else "")
        if choice == "currency":
            try:
                await interaction.response.send_modal(CurrencySettingsModal())
            except Exception as e:
                await safe_reply(interaction, f"No pude abrir el formulario: {e}")


@settings_group.command(name="menu", description="Abrir un menú interactivo de configuración")
async def settings_menu(interaction: discord.Interaction):
    if not interaction.guild:
        await safe_reply(interaction, "Este comando debe usarse en un servidor.")
        return
    view = SettingsMenuView(author_id=interaction.user.id)
    await interaction.response.send_message(
        "Menú de configuración: elige una opción para abrir el formulario.",
        ephemeral=True,
        view=view,
    )


# Slash moderation group for legacy message commands (Discord does not deliver plain messages starting with '/')
m_group = app_commands.Group(name="m", description="Moderation utilities")
try:
    bot.tree.add_command(m_group)
except Exception:
    pass


@m_group.command(name="lock", description="Lock the current text channel so non-staff cannot send messages")
async def slash_m_lock(interaction: discord.Interaction):
    if not interaction.guild:
        await safe_reply(interaction, "This command must be used in a server.")
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await safe_reply(interaction, "This command must be used in a server text channel.")
        return
    try:
        allowed = await is_staff_in_guild(interaction.guild, interaction.user.id)
    except Exception:
        allowed = False
    if not allowed:
        await safe_reply(interaction, "You do not have permission to use this command.")
        return

    staff_role_id = get_staff_role(interaction.guild.id)
    try:
        await apply_lock_channel(interaction.channel, interaction.guild, staff_role_id=staff_role_id)
        await safe_reply(interaction, "Channel locked: only staff can send messages. Viewing permissions were not changed.", ephemeral=False)
    except Exception as e:
        await safe_reply(interaction, f"Failed to lock channel: {e}")


@m_group.command(name="unlock", description="Unlock the current text channel and restore previous permissions")
async def slash_m_unlock(interaction: discord.Interaction):
    if not interaction.guild:
        await safe_reply(interaction, "This command must be used in a server.")
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await safe_reply(interaction, "This command must be used in a server text channel.")
        return
    try:
        allowed = await is_staff_in_guild(interaction.guild, interaction.user.id)
    except Exception:
        allowed = False
    if not allowed:
        await safe_reply(interaction, "You do not have permission to use this command.")
        return

    if interaction.channel.id not in locked_channels:
        await safe_reply(interaction, "Channel is not locked by me or no previous state saved.")
        return
    try:
        await apply_unlock_channel(interaction.channel)
        await safe_reply(interaction, "Channel unlocked and previous send permissions restored.", ephemeral=False)
    except Exception as e:
        await safe_reply(interaction, f"Failed to unlock channel: {e}")


@settings_group.command(name="currency", description="Configure the display name, emoji and balance command name for the currency (UI only)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    name="Currency display name (e.g., Snuggles). Use '-' to reset.",
    emoji="Emoji to display (unicode or server custom emoji <:name:id>). Use '-' to reset.",
    command_name="Slash command name for checking balance (e.g., snuggles). Letters, numbers, _ or - only.",
)
async def settings_currency(
    interaction: discord.Interaction,
    name: str | None = None,
    emoji: str | None = None,
    command_name: str | None = None,
):
    if not interaction.guild:
        await safe_reply(interaction, "This command must be used in a server.")
        return
    # Normalize inputs
    try:
        if name is not None:
            name = name.strip() or None
        if emoji is not None:
            emoji = emoji.strip() or None
        if command_name is not None:
            command_name = command_name.strip().lower() or None
    except Exception:
        pass

    # If nothing provided, show current settings
    if name is None and emoji is None and command_name is None:
        e, n = get_currency_display(interaction.guild.id)
        cur_cmd = get_currency_command_name(interaction.guild.id)
        await safe_reply(interaction, f"Current currency display: {e} {n}  |  Balance command: `/{cur_cmd}` (UI only)")
        return

    # Allow clearing back to defaults by passing '-' for any field
    if name == '-':
        name = None
    if emoji == '-':
        emoji = None
    if command_name == '-':
        command_name = None

    try:
        # Merge with existing values to avoid wiping the other field
        cur_emoji, cur_name = get_currency_display(interaction.guild.id)
        new_name = cur_name if name is None else name
        new_emoji = cur_emoji if emoji is None else emoji
        set_currency_display(interaction.guild.id, new_name, new_emoji)

        # Handle command rename if requested
        cmd_info = ""
        if command_name:
            import re as _re
            if not _re.match(r'^[\w-]{1,32}$', command_name):
                await safe_reply(interaction, f"Invalid command name `{command_name}`: use only letters, numbers, _ or - (1–32 chars).")
                return
            old_cmd = get_currency_command_name(interaction.guild.id)
            set_currency_command_name(interaction.guild.id, command_name)
            try:
                await _apply_guild_currency_command(
                    interaction.guild.id, command_name, old_cmd if old_cmd != command_name else None
                )
                cmd_info = f"  |  Balance command renamed to `/{command_name}`"
            except Exception as ce:
                cmd_info = f"  |  ⚠️ Error registering command: {ce}"

        await safe_reply(interaction, f"Updated currency display: {new_emoji} {new_name} (UI only){cmd_info}")
    except Exception as e:
        await safe_reply(interaction, f"Failed to update currency settings: {e}")


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


@settings_group.command(name="show", description="Show key server settings (currency, staff role, mod roles)")
async def settings_show(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    gid = interaction.guild.id
    try:
        emoji, cname = get_currency_display(gid)
    except Exception:
        emoji, cname = DEFAULT_CURRENCY_EMOJI, DEFAULT_CURRENCY_NAME
    try:
        staff_role_id = get_staff_role(gid)
    except Exception:
        staff_role_id = None

    try:
        ban_role_id = get_mod_role(gid, 'ban')
        kick_role_id = get_mod_role(gid, 'kick')
        mute_role_id = get_mod_role(gid, 'mute')
    except Exception:
        ban_role_id = kick_role_id = mute_role_id = None

    staff_txt = f"<@&{staff_role_id}>" if staff_role_id else "(not set)"
    lines = [
        f"Currency: {emoji} {cname} (UI only)",
        f"Staff role: {staff_txt}",
        f"Mod role (ban): {f'<@&{ban_role_id}>' if ban_role_id else '(not set)'}",
        f"Mod role (kick): {f'<@&{kick_role_id}>' if kick_role_id else '(not set)'}",
        f"Mod role (mute): {f'<@&{mute_role_id}>' if mute_role_id else '(not set)'}",
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@settings_group.command(name="mod_role", description="(Owner/Admin) Configure which role can use ban/kick/mute")
@app_commands.describe(command="Which command to set (ban/kick/mute)", role="Role to allow (omit to clear)")
async def settings_mod_role(interaction: discord.Interaction, command: str, role: discord.Role | None = None):
    if not interaction.guild:
        await safe_reply(interaction, 'This command must be used in a guild (server).')
        return
    # only allow owner or administrators
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


@settings_group.command(name="language", description="Set the language for command descriptions (en/es)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(lang="Language code: 'en' for English, 'es' for Spanish")
@app_commands.choices(lang=[
    app_commands.Choice(name="English (en)", value="en"),
    app_commands.Choice(name="Español (es)", value="es"),
])
async def settings_language(interaction: discord.Interaction, lang: app_commands.Choice[str]):
    if not interaction.guild:
        await safe_reply(interaction, "This command must be used in a server.")
        return
    chosen = lang.value
    set_guild_language(interaction.guild.id, chosen)
    try:
        await _apply_guild_language(interaction.guild.id, chosen)
        lang_name = "English" if chosen == "en" else "Español"
        await safe_reply(
            interaction,
            f"Command descriptions set to **{lang_name}**. "
            f"The changes will be visible in Discord after a few seconds.\n"
            f"*(Only descriptions change — balances and data are untouched.)*",
            ephemeral=True,
        )
    except Exception as e:
        await safe_reply(interaction, f"Failed to apply language: {e}")


async def update_tournament_message(message: discord.Message):
    """Update the embed of the tournament message to reflect current participants."""
    msg_id = message.id
    participants = tournaments.get(msg_id, set())
    embed = message.embeds[0]
    # Rebuild the description with updated participant count and list
    base_description = (embed.description or "").split("\n\n", 1)[0]
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
    # Announce spin and turkeys award (100% probability)
    participants_count = len(participants)
    turkeys_awarded = max(1, 2 * participants_count)
    try:
        await interaction.response.send_message(f"Spinning the wheel... 🎡 Winner will receive {fmt_currency(getattr(interaction.guild, 'id', None), turkeys_awarded)}.", ephemeral=False)
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
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO wins_global(user_id, wins) VALUES (%s, 1) ON CONFLICT(user_id) DO UPDATE SET wins = wins_global.wins + 1", (winner_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Award turkeys to the winner (unless staff)
    try:
        try:
            if await is_staff_in_guild(interaction.guild, winner_id):
                try:
                    _emoji, _cname = get_currency_display(getattr(interaction.guild, 'id', None))
                    await channel.send(f"{_emoji} {winner_mention} is staff and has unlimited {_cname} — congratulations!")
                except Exception:
                    pass
            else:
                add_turkeys(getattr(interaction.guild, 'id', 0) or 0, winner_id, turkeys_awarded)
                try:
                    await channel.send(f"{fmt_currency(getattr(interaction.guild, 'id', None), turkeys_awarded)} have been awarded to {winner_mention}!")
                except Exception:
                    pass
        except Exception:
            # fallback: award normally
            try:
                add_turkeys(getattr(interaction.guild, 'id', 0) or 0, winner_id, turkeys_awarded)
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
        # track current turn interaction view/message so we can disable on advance
        self._current_turn_message_id: int | None = None
        self._current_turn_view: "HouseTurnView" | None = None

    def init_map(self, width: int = 3, height: int = 3):
        """Initialize a simple rectangular map and place players in the center by default."""
        self.map = {"width": width, "height": height, "rooms": {}, "exit_pos": (0, 0), "exit_locked": True}
        for x in range(width):
            for y in range(height):
                # simple flavour descriptions; could be expanded later
                desc = f"A creaky room at ({x+1},{y+1}) with dusty floor and old wallpaper."
                # randomly vary a little
                if (x + y) % 3 == 0:
                    desc = f"A cold room at ({x+1},{y+1}) with a faint whispering sound."
                self.map["rooms"][(x, y)] = {"desc": desc, "items": []}
        # mark an exit door at exit_pos
        ex = self.map["exit_pos"]
        if ex in self.map["rooms"]:
            self.map["rooms"][ex]["desc"] = "A heavy wooden door with an ancient lock. It might open with the right key."
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


# ---------------- Shared action execution for House game (slash + buttons) ----------------
def execute_house_action(game: HouseGame, uid: int, action: str, target: str | None) -> tuple[str, bool]:
    """Execute an action for a player and return (narration, ended).

    Returns a tuple where `ended` is True if the action finished the game
    (for example, unlocking the exit). Does NOT advance the turn index; caller is responsible.
    """
    action = (action or "").strip().lower()
    # movement direction normalization (includes spanish shortcuts)
    dir_aliases = {"up", "down", "left", "right", "u", "d", "l", "r",
                   "arriba", "abajo", "izquierda", "derecha", "arr", "abj", "izq", "der"}
    # allow bare direction as action
    if action in dir_aliases and not target:
        target = action
        action = "move"
    if (not action) and target and target.lower() in dir_aliases:
        action = "move"

    # Helper lambdas
    def normalize_direction(dir_raw: str) -> str:
        d = dir_raw.lower().strip()
        mapping = {
            "u": "up", "up": "up", "arriba": "up", "arr": "up",
            "d": "down", "down": "down", "abajo": "down", "abj": "down",
            "l": "left", "left": "left", "izquierda": "left", "izq": "left",
            "r": "right", "right": "right", "derecha": "right", "der": "right"
        }
        return mapping.get(d, d)

    if action == "search":
        roll = random.random()
        if roll < 0.2:
            item = "ancient key"
            game.players[uid]["inventory"].append(item)
            return f"You search the room and find an **{item}**!", False
        elif roll < 0.4:
            dmg = random.randint(1, 3)
            game.players[uid]["hp"] -= dmg
            return f"A hidden snare grazes you! You take {dmg} damage. (HP now {game.players[uid]['hp']})", False
        else:
            return "You search but find nothing useful. The house groans...", False

    if action == "explore":
        pos = game.players[uid].get("position")
        if pos and game.map:
            x, y = pos
            room = game.map["rooms"].get((x, y), {})
            items = room.get("items", [])
            items_text = ", ".join(items) if items else "none"
            moves = game.valid_moves_for(uid)
            extra = ""
            if tuple(pos) == tuple(game.map.get("exit_pos")):
                if game.map.get("exit_locked", True):
                    extra = " The door is locked; perhaps an ancient key could open it."
                else:
                    extra = " The exit door is unlocked! You can leave any time (narratively)."
            return f"You explore the room ({x+1},{y+1}): {room.get('desc', 'An empty room.')}{extra}. Items: {items_text}. You can move: {', '.join(moves) if moves else 'nowhere'}.", False
        return "You feel disoriented. There's nothing here.", False

    if action == "move":
        if not target:
            return "Specify a direction: up/down/left/right.", False
        direction = normalize_direction(target)
        moved = game.move_player(uid, direction)
        if moved:
            pos = game.players[uid]["position"]
            room = game.map["rooms"].get(pos, {})
            return f"You move {direction} to room ({pos[0]+1},{pos[1]+1}). {room.get('desc', '')}", False
        moves = game.valid_moves_for(uid)
        return f"Cannot move {direction}. Valid moves: {', '.join(moves) if moves else 'none'}.", False

    if action == "use":
        if not target:
            return "Specify an item to use (e.g. key).", False
        item = target.lower()
        inv = game.players[uid].get("inventory", [])
        if item in inv:
            if item in ("ancient key", "key"):
                pos = game.players[uid].get("position")
                exit_pos = game.map.get("exit_pos")
                if pos and exit_pos and tuple(pos) == tuple(exit_pos):
                    if game.map.get("exit_locked", True):
                        inv.remove(item)
                        game.map["exit_locked"] = False
                        # mark game finished; caller should run end_game
                        game.state = "finished"
                        return "You insert the ancient key and unlock the heavy door. It swings open — you escape the Haunted House!", True
                    else:
                        return "The exit door is already unlocked.", False
                else:
                    return "You try the key here, but there's no matching lock in this room.", False
            return f"You try to use {item} but nothing obvious happens.", False
        return f"You don't have {item} in your inventory.", False

    return "Action not recognized. Supported: search, explore, move, use.", False


class HouseTurnView(discord.ui.View):
    """Interactive buttons for a single player's turn in the House game."""
    def __init__(self, game: HouseGame, acting_uid: int):
        super().__init__(timeout=None)
        self.game = game
        self.acting_uid = acting_uid
        # Dynamically add movement buttons based on valid moves
        moves = game.valid_moves_for(acting_uid)
        # order for consistency
        order = ["up", "down", "left", "right"]
        for m in order:
            if m in moves:
                btn = discord.ui.Button(label=m.capitalize(), style=discord.ButtonStyle.primary, custom_id=f"house_move_{m}")
                async def cb(interaction: discord.Interaction, direction=m):  # type: ignore
                    if not await self.interaction_check(interaction):
                        return
                    await self._handle_action(interaction, "move", direction)
                btn.callback = cb  # type: ignore
                self.add_item(btn)
        # Basic action buttons with callbacks
        async def explore_cb(interaction: discord.Interaction):
            if not await self.interaction_check(interaction):
                return
            await self._handle_action(interaction, "explore")
        btn_explore = discord.ui.Button(label="Explore", style=discord.ButtonStyle.secondary, custom_id="house_explore")
        btn_explore.callback = explore_cb  # type: ignore
        self.add_item(btn_explore)

        async def search_cb(interaction: discord.Interaction):
            if not await self.interaction_check(interaction):
                return
            await self._handle_action(interaction, "search")
        btn_search = discord.ui.Button(label="Search", style=discord.ButtonStyle.secondary, custom_id="house_search")
        btn_search.callback = search_cb  # type: ignore
        self.add_item(btn_search)

        # Use button will open a Select menu if there are items
        async def use_cb(interaction: discord.Interaction):
            if not await self.interaction_check(interaction):
                return
            inv = self.game.players.get(self.acting_uid, {}).get("inventory", [])
            if not inv:
                await interaction.response.send_message("You have no items in your inventory.", ephemeral=True)
                return
            # Build a small view with a Select to choose item
            select_view = discord.ui.View(timeout=60)
            options = [discord.SelectOption(label=item, value=item) for item in inv[:25]]
            class UseSelect(discord.ui.Select):
                def __init__(self):
                    super().__init__(placeholder="Select an item...", options=options, min_values=1, max_values=1)
                async def callback(self, inter: discord.Interaction):  # type: ignore
                    if inter.user.id != interaction.user.id:
                        await inter.response.send_message("You cannot use another player's inventory.", ephemeral=True)
                        return
                    choice = self.values[0]
                    narration, ended = execute_house_action(self.view.parent_game, self.view.parent_uid, "use", choice)  # type: ignore
                    # disable original turn view and advance (will also send narration)
                    await self.view.parent_view.disable_and_advance(inter, narration=narration)  # type: ignore
                    # if this ended the game, call end_game and include winner name
                    if ended:
                        try:
                            # store winner display name for announcement
                            self.view.parent_game._last_winner_display_name = interaction.user.display_name
                        except Exception:
                            pass
                        try:
                            await end_game(self.view.parent_game, announce=True, delete_channel=False)
                        except Exception:
                            pass
            # attach helpers to view for callback context
            select = UseSelect()
            select_view.add_item(select)
            # attach references
            setattr(select_view, 'parent_game', self.game)
            setattr(select_view, 'parent_uid', self.acting_uid)
            setattr(select_view, 'parent_view', self)
            await interaction.response.send_message("Choose an item to use:", view=select_view, ephemeral=True)
        btn_use = discord.ui.Button(label="Use", style=discord.ButtonStyle.success, custom_id="house_use")
        btn_use.callback = use_cb  # type: ignore
        self.add_item(btn_use)

        async def skip_cb(interaction: discord.Interaction):
            if not await self.interaction_check(interaction):
                return
            await self.disable_and_advance(interaction, narration="You skip your turn, the house creaks ominously.")
        btn_skip = discord.ui.Button(label="Skip", style=discord.ButtonStyle.danger, custom_id="house_skip")
        btn_skip.callback = skip_cb  # type: ignore
        self.add_item(btn_skip)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the acting player to click; others get ephemeral error
        if interaction.user.id != self.acting_uid:
            try:
                await interaction.response.send_message("It's not your turn (please wait).", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logging.exception("Error en HouseTurnView", exc_info=error)
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("An error occurred with the button.", ephemeral=True)
            except Exception:
                pass

    async def disable_and_advance(self, interaction: discord.Interaction, narration: str | None = None):
        # Disable buttons
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        # Edit the original turn message to reflect disabled state. Prefer stored message id
        try:
            ch = self.game.guild.get_channel(self.game.channel_id) if self.game.channel_id else None
            if ch and self.game._current_turn_message_id:
                try:
                    orig = await ch.fetch_message(self.game._current_turn_message_id)
                    await orig.edit(view=self)
                except Exception:
                    # fallback to editing interaction.message if available
                    try:
                        await interaction.message.edit(view=self)
                    except Exception:
                        pass
            else:
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
        except Exception:
            pass
        # Send narration to channel
        if narration:
            try:
                ch = self.game.guild.get_channel(self.game.channel_id) if self.game.channel_id else None
                if ch:
                    await ch.send(f"**{interaction.user.display_name}**: {narration}")
            except Exception:
                pass
        # Advance turn
        accepted = self.game.accepted_players()
        if accepted:
            self.game.turn_index = (self.game.turn_index + 1) % max(1, len(accepted))
        self.game._last_prompt_turn = None
        self.game._current_turn_view = None
        self.game._current_turn_message_id = None
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("Action registered.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Inventory", style=discord.ButtonStyle.success, custom_id="house_inventory")
    async def inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
        inv = self.game.players.get(self.acting_uid, {}).get("inventory", [])
        inv_text = ", ".join(inv) if inv else "(empty)"
        try:
            await interaction.response.send_message(f"Inventory: {inv_text}", ephemeral=True)
        except Exception:
            pass

    async def _handle_action(self, interaction: discord.Interaction, action: str, target: str | None = None):
        narration, ended = execute_house_action(self.game, self.acting_uid, action, target)
        if ended:
            # disable view and then run end_game (include winner name)
            try:
                await self.disable_and_advance(interaction, narration=narration)
            except Exception:
                pass
            try:
                self.game._last_winner_display_name = interaction.user.display_name
            except Exception:
                pass
            try:
                await end_game(self.game, announce=True, delete_channel=False)
            except Exception:
                pass
            return
        await self.disable_and_advance(interaction, narration=narration)

    async def on_timeout(self):
        # If not advanced manually, auto-skip (this won't fire since timeout=None) kept for future use
        pass

    # We rely on per-button callbacks above; no generic dispatcher needed


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
    # For multiplayer mode, a default of 1 is confusing (would be full immediately).
    # If the user requested multi and left default, bump to a sensible minimum (4).
    if mode == "multi" and max_players <= 1:
        max_players = 5
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
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
    # add invited player as not accepted yet
    game.players[target_member.id] = {"accepted": False, "hp": 10, "inventory": [], "position": None}

    # DM the invite with instructions
    async def send_invite_dm(member: discord.Member):
        text = (
            f"You have been invited to a House game by {interaction.user.display_name}.\n"
            f"To accept: go to the server and run /house accept OR reply here with /house accept if commands are enabled in DMs.\n"
            f"Channel: {interaction.guild.get_channel(game.channel_id).mention if interaction.guild.get_channel(game.channel_id) else 'N/A'}"
        )
        try:
            # Use Member.send which internally opens the DM channel ensuring permissions
            await member.send(text)
            return True
        except discord.Forbidden:
            logging.info(f"DM blocked or privacy settings for user {member.id}; falling back to channel mention.")
        except discord.HTTPException as e:
            logging.warning(f"Failed sending DM to {member.id}: {e}")
        return False

    sent_dm = False
    try:
        sent_dm = await send_invite_dm(target_member)
    except Exception:
        sent_dm = False
    if not sent_dm:
        # fallback: public notice in lobby channel (game channel or invoking channel)
        lobby_channel = interaction.guild.get_channel(game.channel_id) or interaction.channel
        if lobby_channel:
            try:
                await lobby_channel.send(f"<@{target_member.id}> could not be DM'd. They have been invited — please ask them to run `/house accept` to join.")
            except Exception:
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
        # Apply member-specific overwrites in a single edit to avoid many PUTs
        try:
            original_overwrites = dict(ch.overwrites)
        except Exception:
            original_overwrites = {}
        new_overwrites = dict(original_overwrites)
        for uid in accepted:
            try:
                member = await game.guild.fetch_member(uid)
            except Exception:
                member = None
            if member:
                new_overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        async with permission_op_lock:
            try:
                await ch.edit(overwrites=new_overwrites)
            except Exception:
                # fallback to per-member set_permissions
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
    intro_lines.append("When it's your turn you'll receive a prompt in this channel. You can USE THE BUTTONS or the commands `/house action move <direction>`, `/house action explore`, `/house action search`. Directions: up/down/left/right.")
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

    # Execute action and narrate using shared function
    narration, ended = execute_house_action(game, interaction.user.id, action, target)
    ch = game.guild.get_channel(game.channel_id) if game.channel_id else None
    if ch:
        try:
            await ch.send(f"**{interaction.user.display_name}**: {narration}")
        except Exception:
            pass
    await interaction.response.send_message("Action registered.", ephemeral=True)
    if ended:
        try:
            game._last_winner_display_name = interaction.user.display_name
        except Exception:
            pass
        try:
            await end_game(game, announce=True, delete_channel=False)
        except Exception:
            pass
        return
    # advance turn
    accepted = game.accepted_players()
    game.turn_index = (game.turn_index + 1) % max(1, len(accepted))
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
            meta = game.players.get(current_uid, {})
            hp = meta.get("hp", 0)
            pos = meta.get("position")
            pos_text = f"({pos[0]+1},{pos[1]+1})" if pos else "N/A"
            moves = game.valid_moves_for(current_uid)
            moves_text = ", ".join(moves) if moves else "none"
            prompt = (f"It's <@{current_uid}>'s turn — HP: {hp} — Position: {pos_text}. "
                      f"Valid moves: {moves_text if moves_text else 'none'}. Use buttons or commands.")

            # Avoid duplicate prompt for same turn
            if game._last_prompt_turn != game.turn_index:
                # create interactive view for current player's turn
                view = HouseTurnView(game, current_uid)
                try:
                    msg = await ch.send(prompt, view=view)
                    game._current_turn_message_id = msg.id
                    game._current_turn_view = view
                except Exception:
                    # fallback without view
                    try:
                        await ch.send(prompt)
                    except Exception:
                        pass
                game._last_prompt_turn = game.turn_index

            # Wait for up to 25s for buttons or slash action to advance
            waited = 0
            while waited < 25 and game.state == "started" and game._last_prompt_turn == game.turn_index:
                await asyncio.sleep(5)
                waited += 5

            # If still same turn (no interaction), auto-skip
            if game._last_prompt_turn == game.turn_index:
                narration = "Time's up. The turn is skipped and the house creaks in the dark."
                try:
                    await ch.send(f"**Auto**: {narration}")
                except Exception:
                    pass
                # Advance turn
                if accepted:
                    game.turn_index = (game.turn_index + 1) % max(1, len(accepted))
                game._last_prompt_turn = None
                # disable previous view if exists
                if game._current_turn_view and game._current_turn_message_id:
                    try:
                        for child in game._current_turn_view.children:
                            if isinstance(child, discord.ui.Button):
                                child.disabled = True
                        msg = await ch.fetch_message(game._current_turn_message_id)
                        await msg.edit(view=game._current_turn_view)
                    except Exception:
                        pass
                    game._current_turn_view = None
                    game._current_turn_message_id = None
        game.state = "finished"
        try:
            await end_game(game, announce=True, delete_channel=False)
        except Exception:
            # fallback: send simple message
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

# Furby tournament command removed.


def _current_date_str():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _cleanup_old_schedule():
    """Remove schedule entries older than today (UTC-based daily reset)."""
    today = _current_date_str()
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule_entries WHERE date < %s", (today,))
    conn.commit()
    conn.close()


def local_slot_to_utc(slot: int, tz_name: str, local_date: Optional[date] = None):
    """Convert a user-selected slot (1-24) in given timezone to UTC date and slot.
    Returns (utc_date_str, utc_slot_int, utc_dt, local_dt)."""
    if slot < 1 or slot > 24:
        raise ValueError("slot must be between 1 and 24")
    user_tz = ZoneInfo(tz_name)
    if local_date is None:
        local_date = datetime.now(user_tz).date()
    local_dt = datetime(local_date.year, local_date.month, local_date.day, slot - 1, 0, 0, tzinfo=user_tz)
    utc_dt = local_dt.astimezone(timezone.utc)
    utc_date = utc_dt.strftime("%Y-%m-%d")
    utc_slot = utc_dt.hour
    return utc_date, utc_slot, utc_dt, local_dt


schedule_group = app_commands.Group(name="schedule", description="Show or add schedule signups")


@schedule_group.command(name="show", description="Show today's schedule (24 slots) — shows viewer-local and user-selected local times")
async def show_schedule(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server (guild).", ephemeral=True)
        return
    await interaction.response.defer()
    _cleanup_old_schedule()

    # Viewer settings define which local day and slot labels (1-24) are shown.
    user_tz_name = get_user_timezone(interaction.user.id) or "Etc/UTC"
    user_fmt = get_user_time_format(interaction.user.id)
    user_tz = ZoneInfo(user_tz_name)
    time_str_fmt = "%I:%M %p" if user_fmt == "12h" else "%H:%M"
    local_today = datetime.now(user_tz).date()
    local_start = datetime(local_today.year, local_today.month, local_today.day, 0, 0, 0, tzinfo=user_tz)
    local_end = local_start + timedelta(days=1)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)
    utc_date_start = utc_start.strftime("%Y-%m-%d")
    utc_date_end = (utc_end - timedelta(seconds=1)).strftime("%Y-%m-%d")

    guild_id = getattr(interaction.guild, 'id', 0) or 0
    conn = get_db_conn()
    cur = conn.cursor()
    if utc_date_start == utc_date_end:
        cur.execute(
            "SELECT date, slot, user_id, game, local_tz, local_slot FROM schedule_entries WHERE guild_id = %s AND date = %s ORDER BY date, slot",
            (guild_id, utc_date_start),
        )
    else:
        cur.execute(
            "SELECT date, slot, user_id, game, local_tz, local_slot FROM schedule_entries WHERE guild_id = %s AND date IN (%s, %s) ORDER BY date, slot",
            (guild_id, utc_date_start, utc_date_end),
        )
    rows = cur.fetchall()
    conn.close()

    # Re-bucket UTC rows into viewer-local slots for the viewer's local day.
    slots = {i: [] for i in range(24)}
    for row_date, utc_slot, user_id, game, local_tz, local_slot in rows:
        try:
            slot_utc = datetime.strptime(f"{row_date} {utc_slot:02d}:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        slot_local_for_viewer = slot_utc.astimezone(user_tz)
        if slot_local_for_viewer.date() != local_today:
            continue
        slots[slot_local_for_viewer.hour].append((user_id, game, local_tz, slot_utc))

    desc_lines = []
    for hour in range(24):
        slot_local = datetime(local_today.year, local_today.month, local_today.day, hour, 0, 0, tzinfo=user_tz)
        time_token = slot_local.strftime(time_str_fmt)
        entries = slots.get(hour) or []
        if entries:
            parts = []
            for uid, game, entry_tz_name, slot_utc in entries:
                try:
                    entry_tz = ZoneInfo(entry_tz_name or "Etc/UTC")
                except Exception:
                    entry_tz = timezone.utc
                entry_local = slot_utc.astimezone(entry_tz)
                entry_time_token = entry_local.strftime(time_str_fmt)
                tz_display = entry_tz_name or "Etc/UTC"
                parts.append(f"<@{uid}> ({game}) — {entry_time_token} ({tz_display})")
            entry_text = ", ".join(parts)
        else:
            entry_text = "(empty)"
        slot_label = hour + 1
        desc_lines.append(f"**{slot_label}** — {time_token} : {entry_text}")

    fmt_label = "12h (AM/PM)" if user_fmt == "12h" else "24h"
    embed = discord.Embed(
        title=f"Schedule ({fmt_label}, {user_tz_name})",
        description="\n".join(desc_lines),
        color=0x00BFFF,
    )
    await interaction.followup.send(embed=embed)


@schedule_group.command(name="add", description="Add yourself to a numbered slot (1-24)")
@app_commands.describe(slot="Slot number 1-24", game="Game or note to add")
async def add_schedule(interaction: discord.Interaction, slot: int, game: str):
    # normalize slot to 1-24 and convert to 0-23 index for storage
    if slot < 1 or slot > 24:
        await interaction.response.send_message("Please provide a slot number between 1 and 24.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server (guild).", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    # Normalize selected slot (1-24) from user's timezone to UTC date/slot.
    user_tz_name = get_user_timezone(interaction.user.id) or "Etc/UTC"
    try:
        utc_date, utc_slot, utc_dt, local_dt = local_slot_to_utc(slot, user_tz_name)
    except Exception:
        # fallback: interpret as same-hour UTC now
        now_utc = datetime.now(timezone.utc)
        utc_date = now_utc.strftime("%Y-%m-%d")
        utc_slot = now_utc.hour
        utc_dt = now_utc
        try:
            local_dt = now_utc.astimezone(ZoneInfo(user_tz_name))
        except Exception:
            local_dt = now_utc

    _cleanup_old_schedule()
    guild_id = getattr(interaction.guild, 'id', 0) or 0
    conn = get_db_conn()
    cur = conn.cursor()
    # Upsert using UTC-normalized date and slot
    try:
        cur.execute(
            "INSERT INTO schedule_entries(date, slot, guild_id, user_id, game, local_tz, local_slot) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (utc_date, utc_slot, guild_id, interaction.user.id, game, user_tz_name, slot),
        )
        conn.commit()
    except Exception as e:
        print("DB error adding schedule:", e)
    finally:
        conn.close()

    # Build a timestamp from the UTC datetime so Discord shows it localized for each viewer
    slot_ts = int(utc_dt.timestamp())
    await interaction.followup.send(
        f"Added you to slot **{slot}** ({user_tz_name} {local_dt.strftime('%Y-%m-%d %H:%M')}) — stored as UTC **{utc_slot+1}** (<t:{slot_ts}:t>) for '{game}'. Use `/schedule show` to view."
    )


# register the group with the bot's command tree
try:
    bot.tree.add_command(schedule_group)
except Exception:
    # in case adding twice or running in reload scenarios
    pass


@schedule_group.command(name="delete", description="Remove your signup from a numbered slot (1-24)")
@app_commands.describe(slot="Slot number 1-24 to remove your signup from")
async def delete_schedule(interaction: discord.Interaction, slot: int):
    """Delete the invoking user's signup for the given slot on the user's local day."""
    if slot < 1 or slot > 24:
        await interaction.response.send_message("Please provide a slot number between 1 and 24.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server (guild).", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    user_tz_name = get_user_timezone(interaction.user.id) or "Etc/UTC"
    try:
        utc_date, utc_slot, utc_dt, _local_dt = local_slot_to_utc(slot, user_tz_name)
    except Exception:
        now_utc = datetime.now(timezone.utc)
        utc_date = now_utc.strftime("%Y-%m-%d")
        utc_slot = now_utc.hour
        utc_dt = now_utc

    _cleanup_old_schedule()
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        guild_id = getattr(interaction.guild, 'id', 0) or 0
        cur.execute(
            "DELETE FROM schedule_entries WHERE date = %s AND slot = %s AND guild_id = %s AND user_id = %s",
            (utc_date, utc_slot, guild_id, interaction.user.id),
        )
        deleted = cur.rowcount
        conn.commit()
    except Exception as e:
        print("DB error deleting schedule:", e)
        deleted = 0
    finally:
        conn.close()

    if deleted:
        slot_ts = int(utc_dt.timestamp())
        await interaction.followup.send(f"Removed your signup from slot **{slot}** (<t:{slot_ts}:t>). Use `/schedule show` to view.")
    else:
        await interaction.followup.send(f"No signup found for you in slot {slot}. Use `/schedule show` to check current signups.")


# ──────────────────────────────────────────────────────────────────────────────
# MONOPOLY GO – auto-poster of official free reward links
# ──────────────────────────────────────────────────────────────────────────────

# Patterns that identify a Monopoly Go reward deep-link / short-link.
# Sourced from known Scopely / AppsFlyer / Jambl URL formats.
import re as _re
_MONOPOLY_LINK_PATTERNS = [
    _re.compile(r'https?://monopolygo\.com/', _re.I),
    _re.compile(r'https?://mply\.io/', _re.I),
    _re.compile(r'https?://monopolygo\.onelink\.me/', _re.I),
    _re.compile(r'https?://board-kings\.onelink\.me/[^"\'>\s]*monopolygo', _re.I),
    _re.compile(r'https?://[^\s"\'<>]*scopely\.com/[^\s"\'<>]*monopoly', _re.I),
    _re.compile(r'https?://[^\s"\'<>]*monopoly[_-]?go[^\s"\'<>]*\?.*reward', _re.I),
]
# Human-readable aggregator pages that are kept up-to-date with official links.
_MONOPOLY_SOURCES = [
    "https://www.pocketgamer.com/monopoly-go/free-dice/",
    "https://progameguides.com/monopoly-go/monopoly-go-free-dice-links/",
    "https://www.videogamer.com/guides/monopoly-go-free-dice-links/",
]
_MONOPOLY_POLL_INTERVAL = 3600  # seconds between polls (1 hour)


def _is_monopoly_reward_link(url: str) -> bool:
    return any(p.search(url) for p in _MONOPOLY_LINK_PATTERNS)


async def _fetch_monopoly_links_from_source(session, url: str) -> list[str]:
    """Fetch a single aggregator page and return all Monopoly Go reward URLs found."""
    try:
        async with session.get(url, timeout=15, allow_redirects=True) as resp:
            if resp.status != 200:
                return []
            html = await resp.text(errors="replace")
    except Exception as e:
        logging.warning(f"[MonopolyGo] Failed to fetch {url}: {e}")
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        found = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if _is_monopoly_reward_link(href):
                found.append(href)
        # Also scan raw text for pasted links (some sites use <p> or <li> text)
        for text_node in soup.find_all(string=_re.compile(r'https?://', _re.I)):
            for token in text_node.split():
                t = token.strip('.,;)([]"\' ')
                if _is_monopoly_reward_link(t):
                    found.append(t)
        return list(dict.fromkeys(found))  # deduplicate order-preserving
    except Exception as e:
        logging.warning(f"[MonopolyGo] Parse error for {url}: {e}")
        return []


def _monopoly_already_posted(url: str) -> bool:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM monopoly_go_posted WHERE url = %s", (url,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def _monopoly_mark_posted(url: str):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO monopoly_go_posted (url, posted_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (url, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def _monopoly_get_channels() -> list[tuple[int, int]]:
    """Return list of (guild_id, channel_id) for all configured guilds."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT guild_id, channel_id FROM monopoly_go_config")
    rows = cur.fetchall()
    conn.close()
    return rows


async def _monopoly_poster_loop():
    """Background task: polls aggregator sources and posts new reward links."""
    await bot.wait_until_ready()
    # lazy import – only needed at runtime
    try:
        import aiohttp
    except ImportError:
        logging.error("[MonopolyGo] aiohttp not installed – auto-poster disabled. Run: pip install aiohttp beautifulsoup4")
        return
    try:
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        logging.error("[MonopolyGo] beautifulsoup4 not installed – auto-poster disabled. Run: pip install aiohttp beautifulsoup4")
        return

    logging.info("[MonopolyGo] Auto-poster started.")
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (compatible; MonopolyGoBot/1.0)"}) as session:
        while not bot.is_closed():
            try:
                guild_channels = _monopoly_get_channels()
                if guild_channels:
                    new_links: list[str] = []
                    for source_url in _MONOPOLY_SOURCES:
                        links = await _fetch_monopoly_links_from_source(session, source_url)
                        for link in links:
                            if not _monopoly_already_posted(link):
                                new_links.append(link)

                    # Deduplicate across sources
                    seen: set[str] = set()
                    unique_new: list[str] = []
                    for lnk in new_links:
                        if lnk not in seen:
                            seen.add(lnk)
                            unique_new.append(lnk)

                    if unique_new:
                        for link in unique_new:
                            _monopoly_mark_posted(link)
                            embed = discord.Embed(
                                title="🎲 Monopoly GO — Free Reward Link!",
                                description=link,
                                color=0xE91E63,
                                url=link,
                            )
                            embed.set_footer(text="Tap the link to claim your free reward • Monopoly GO")
                            for _guild_id, _channel_id in guild_channels:
                                try:
                                    ch = bot.get_channel(_channel_id)
                                    if ch is None:
                                        ch = await bot.fetch_channel(_channel_id)
                                    await ch.send(embed=embed)
                                    logging.info(f"[MonopolyGo] Posted {link} to channel {_channel_id}")
                                except Exception as e:
                                    logging.warning(f"[MonopolyGo] Failed to post to channel {_channel_id}: {e}")
            except Exception as e:
                logging.exception(f"[MonopolyGo] Unexpected error in poster loop: {e}")
            await asyncio.sleep(_MONOPOLY_POLL_INTERVAL)


@bot.tree.command(name="setmonopolychannel", description="Set the channel where Monopoly GO free reward links will be posted")
@app_commands.describe(channel="The text channel to post Monopoly GO reward links in")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_monopoly_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO monopoly_go_config (guild_id, channel_id) VALUES (%s, %s) ON CONFLICT(guild_id) DO UPDATE SET channel_id = %s",
            (interaction.guild.id, channel.id, channel.id)
        )
        conn.commit()
    finally:
        conn.close()
    await interaction.response.send_message(
        f"✅ Monopoly GO reward links will be auto-posted in {channel.mention}.\n"
        "The bot checks official sources every 3 minutes and posts each link only once.",
        ephemeral=True
    )


@bot.tree.command(name="unsetmonopolychannel", description="Disable automatic Monopoly GO reward link posting in this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def unset_monopoly_channel(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM monopoly_go_config WHERE guild_id = %s", (interaction.guild.id,))
        deleted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if deleted:
        await interaction.response.send_message("✅ Monopoly GO auto-posting disabled for this server.", ephemeral=True)
    else:
        await interaction.response.send_message("No Monopoly GO channel was configured for this server.", ephemeral=True)


@bot.tree.command(name="custom", description="Crea un comando personalizado para este servidor")
@app_commands.describe(
    name="Nombre del comando (se invoca con !nombre)",
    info="Texto que se mostrará al usar el comando"
)
@app_commands.checks.has_permissions(manage_guild=True)
async def custom_command_create(interaction: discord.Interaction, name: str, info: str):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    cmd_name = name.lower().strip()
    if not cmd_name or any(c in cmd_name for c in (' ', '\t', '\n')):
        await interaction.response.send_message("El nombre del comando debe ser una sola palabra sin espacios.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO custom_commands (guild_id, name, info) VALUES (%s, %s, %s) ON CONFLICT(guild_id, name) DO UPDATE SET info = %s",
            (interaction.guild.id, cmd_name, info, info)
        )
        conn.commit()
    finally:
        conn.close()
    await interaction.response.send_message(f"Comando personalizado `!{cmd_name}` creado correctamente.", ephemeral=True)


@bot.tree.command(name="deletecustom", description="Elimina un comando personalizado de este servidor")
@app_commands.describe(name="Nombre del comando personalizado a eliminar")
@app_commands.checks.has_permissions(manage_guild=True)
async def custom_command_delete(interaction: discord.Interaction, name: str):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    cmd_name = name.lower().strip()
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM custom_commands WHERE guild_id = %s AND name = %s",
            (interaction.guild.id, cmd_name)
        )
        deleted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if deleted:
        await interaction.response.send_message(f"Comando personalizado `!{cmd_name}` eliminado.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No se encontró ningún comando personalizado llamado `!{cmd_name}`.", ephemeral=True)


@bot.tree.command(name="set_official_links_channel", description="Configura el canal donde se publicarán los enlaces oficiales")
@app_commands.describe(channel="Canal de texto donde publicar enlaces oficiales")
@app_commands.checks.has_permissions(manage_guild=True)
async def set_official_links_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO settings (guild_id, official_links_channel_id) VALUES (%s, %s) "
            "ON CONFLICT(guild_id) DO UPDATE SET official_links_channel_id = %s",
            (interaction.guild.id, channel.id, channel.id)
        )
        conn.commit()
    finally:
        conn.close()
    await interaction.response.send_message(f"Canal de enlaces oficiales establecido a {channel.mention}", ephemeral=True)


@bot.tree.command(name="add_official_link", description="Añade un enlace oficial (ej: dado gratis/escudo)")
@app_commands.describe(name="Etiqueta corta para el enlace", url="URL pública del enlace")
@app_commands.checks.has_permissions(manage_guild=True)
async def add_official_link(interaction: discord.Interaction, name: str, url: str):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    key = name.lower().strip()
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO official_links (guild_id, name, url) VALUES (%s, %s, %s) ON CONFLICT(guild_id, name) DO UPDATE SET url = %s",
                    (interaction.guild.id, key, url, url))
        conn.commit()
    finally:
        conn.close()
    await interaction.response.send_message(f"Enlace oficial '{key}' guardado.", ephemeral=True)


@bot.tree.command(name="remove_official_link", description="Elimina un enlace oficial por su nombre")
@app_commands.describe(name="Nombre del enlace a eliminar")
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_official_link(interaction: discord.Interaction, name: str):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    key = name.lower().strip()
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM official_links WHERE guild_id = %s AND name = %s", (interaction.guild.id, key))
        deleted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    if deleted:
        await interaction.response.send_message(f"Enlace oficial '{key}' eliminado.", ephemeral=True)
    else:
        await interaction.response.send_message(f"No se encontró ningún enlace llamado '{key}'.", ephemeral=True)


@bot.tree.command(name="list_official_links", description="Lista los enlaces oficiales guardados para este servidor")
@app_commands.checks.has_permissions(manage_guild=True)
async def list_official_links(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, url FROM official_links WHERE guild_id = %s ORDER BY name", (interaction.guild.id,))
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        await interaction.response.send_message("No hay enlaces oficiales guardados para este servidor.", ephemeral=True)
        return
    lines = [f"**{r[0]}** — {r[1]}" for r in rows]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="post_official_links", description="Publica los enlaces oficiales en el canal configurado (o en este canal si no hay configurado)")
@app_commands.checks.has_permissions(manage_guild=True)
async def post_official_links(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Este comando solo se puede usar en un servidor.", ephemeral=True)
        return
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT official_links_channel_id FROM settings WHERE guild_id = %s", (interaction.guild.id,))
        row = cur.fetchone()
        channel_id = row[0] if row and row[0] is not None else None
        cur.execute("SELECT name, url FROM official_links WHERE guild_id = %s ORDER BY name", (interaction.guild.id,))
        links = cur.fetchall()
    finally:
        conn.close()

    if not links:
        await interaction.response.send_message("No hay enlaces oficiales guardados para publicar.", ephemeral=True)
        return

    # Build embed
    embed = discord.Embed(title="Enlaces oficiales - Monopoly GO", color=0x00BFFF)
    desc_lines = [f"**{name}** — {url}" for name, url in links]
    embed.description = "\n".join(desc_lines)

    # Determine destination channel
    dest = None
    try:
        if channel_id:
            dest = interaction.guild.get_channel(channel_id)
    except Exception:
        dest = None
    if not dest:
        dest = interaction.channel

    try:
        await dest.send(embed=embed)
        await interaction.response.send_message(f"Enlaces publicados en {dest.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error al publicar enlaces: {e}", ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────────
# EASTER EGG EVENT
# ──────────────────────────────────────────────────────────────────────────────

# In-memory tracking: message_id -> {"guild_id": int, "claimed": bool}
_active_eggs: dict[int, dict] = {}

# Active event loops per guild: guild_id -> asyncio.Task
_easter_event_tasks: dict[int, asyncio.Task] = {}

# Eligible channels per active event: guild_id -> list[int] (channel ids)
_easter_event_channels: dict[int, list[int]] = {}

_EASTER_MIN_INTERVAL = 300   # 5 minutes
_EASTER_MAX_INTERVAL = 600   # 10 minutes


def _easter_add_egg(guild_id: int, user_id: int, username: str):
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO easter_egg_scores (guild_id, user_id, username, egg_count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (guild_id, user_id)
            DO UPDATE SET egg_count = easter_egg_scores.egg_count + 1,
                          username = EXCLUDED.username
            """,
            (guild_id, user_id, username),
        )
        conn.commit()
    finally:
        conn.close()


async def _spawn_single_egg(guild_id: int) -> bool:
    """Pick a random eligible channel and spawn one egg. Returns True if successful."""
    channel_ids = _easter_event_channels.get(guild_id, [])
    if not channel_ids:
        return False
    # Shuffle so each call is random
    pool = list(channel_ids)
    random.shuffle(pool)
    for ch_id in pool:
        ch = bot.get_channel(ch_id)
        if ch is None:
            continue
        embed = discord.Embed(
            title="🥚 An Easter Egg appeared!",
            description="Be the first to click the button and collect it!\n\n**Only one person can grab it!**",
            color=0xFFD700,
        )
        embed.set_footer(text="Easter Egg Event • First click wins!")
        view = EasterEggView()
        try:
            msg = await ch.send(embed=embed, view=view)
            _active_eggs[msg.id] = {"guild_id": guild_id, "claimed": False}
            return True
        except Exception:
            continue
    return False


async def _easter_loop(guild_id: int):
    """Background task that spawns eggs at random intervals until cancelled."""
    await bot.wait_until_ready()
    try:
        while True:
            delay = random.randint(_EASTER_MIN_INTERVAL, _EASTER_MAX_INTERVAL)
            await asyncio.sleep(delay)
            # Check event is still active
            if guild_id not in _easter_event_channels:
                break
            await _spawn_single_egg(guild_id)
    except asyncio.CancelledError:
        pass


class EasterEggView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🥚 Collect Egg!", style=discord.ButtonStyle.success, custom_id="easter_egg_collect")
    async def collect(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id if interaction.message else None
        if msg_id is None:
            await interaction.response.send_message("Something went wrong.", ephemeral=True)
            return

        egg_data = _active_eggs.get(msg_id)
        if egg_data is None or egg_data.get("claimed"):
            await interaction.response.send_message("This egg has already been collected! 🐣", ephemeral=True)
            return

        # Claim atomically in memory first
        egg_data["claimed"] = True

        guild_id = egg_data["guild_id"]
        user = interaction.user
        username = str(user)
        _easter_add_egg(guild_id, user.id, username)

        # Disable button and update message
        button.disabled = True
        button.label = f"🐣 Collected by {user.display_name}!"
        button.style = discord.ButtonStyle.secondary
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            await interaction.response.send_message("You collected the egg! 🥚", ephemeral=True)


@bot.tree.command(name="start_easter_event", description="Start the Easter egg event — eggs will randomly appear every 5–10 min")
@app_commands.describe(role="The role whose visible channels can receive easter eggs")
@app_commands.checks.has_permissions(manage_guild=True)
async def start_easter_event(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    guild_id = interaction.guild.id

    if guild_id in _easter_event_tasks and not _easter_event_tasks[guild_id].done():
        await interaction.response.send_message(
            "An Easter egg event is already running! Use `/end_easter_event` to stop it first.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    me = interaction.guild.me
    eligible: list[int] = []
    skipped = 0

    for channel in interaction.guild.text_channels:
        role_perms = channel.permissions_for(role)
        if not (role_perms.view_channel and role_perms.send_messages):
            continue
        bot_perms = channel.permissions_for(me)
        if not (bot_perms.send_messages and bot_perms.embed_links):
            skipped += 1
            continue
        eligible.append(channel.id)

    if not eligible:
        await interaction.followup.send(
            "No eligible channels found for that role (no channels where the role can view + interact and the bot can post).",
            ephemeral=True,
        )
        return

    _easter_event_channels[guild_id] = eligible

    # Spawn the very first egg immediately
    await _spawn_single_egg(guild_id)

    # Start background loop
    task = asyncio.create_task(_easter_loop(guild_id))
    _easter_event_tasks[guild_id] = task

    summary = (
        f"🥚 Easter egg event started! First egg has been spawned.\n"
        f"New eggs will appear randomly every **5–10 minutes** across **{len(eligible)}** eligible channel(s).\n"
        f"Use `/end_easter_event` to stop the event and see the leaderboard."
    )
    if skipped:
        summary += f"\n⚠️ Skipped **{skipped}** channel(s) — bot is missing permissions there."
    await interaction.followup.send(summary, ephemeral=True)


@bot.tree.command(name="end_easter_event", description="End the Easter egg event and show the leaderboard")
@app_commands.checks.has_permissions(manage_guild=True)
async def end_easter_event(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    guild_id = interaction.guild.id

    # Stop background loop
    task = _easter_event_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()

    # Remove eligible channels
    _easter_event_channels.pop(guild_id, None)

    # Clear unclaimed eggs from memory
    to_remove = [mid for mid, data in _active_eggs.items() if data["guild_id"] == guild_id]
    for mid in to_remove:
        _active_eggs.pop(mid, None)

    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id, username, egg_count FROM easter_egg_scores WHERE guild_id = %s ORDER BY egg_count DESC",
            (guild_id,),
        )
        rows = cur.fetchall()
        cur.execute("DELETE FROM easter_egg_scores WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()

    if not rows:
        await interaction.response.send_message("The Easter event has ended. No eggs were collected! 🐣", ephemeral=False)
        return

    embed = discord.Embed(
        title="🐣 Easter Egg Event — Final Results",
        color=0xFFD700,
    )
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, username, count) in enumerate(rows):
        medal = medals[i] if i < 3 else f"**#{i+1}**"
        lines.append(f"{medal} <@{user_id}> (`{username}` · ID: `{user_id}`) — **{count}** egg{'s' if count != 1 else ''}")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Total participants: {len(rows)}")

    await interaction.response.send_message(embed=embed)


# ---------------- TIMEZONE COMMANDS (/time + /setmytime) ----------------

_COMMON_TIMEZONES = [
    "Etc/UTC",
    "Europe/Madrid", "Europe/London", "Europe/Paris", "Europe/Berlin",
    "Europe/Rome", "Europe/Amsterdam", "Europe/Lisbon", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Mexico_City",
    "America/Bogota", "America/Lima", "America/Santiago",
    "Asia/Tokyo", "Asia/Shanghai", "Asia/Seoul", "Asia/Singapore",
    "Asia/Dubai", "Asia/Kolkata", "Asia/Jakarta", "Asia/Karachi",
    "Australia/Sydney", "Australia/Melbourne",
    "Pacific/Auckland", "Pacific/Honolulu",
    "Africa/Lagos", "Africa/Cairo", "Africa/Johannesburg",
]

_ALL_TIMEZONES_SORTED: list[str] | None = None


def _get_all_timezones_sorted() -> list[str]:
    global _ALL_TIMEZONES_SORTED
    if _ALL_TIMEZONES_SORTED is None:
        _ALL_TIMEZONES_SORTED = sorted(_all_tz_fn())
    return _ALL_TIMEZONES_SORTED


def get_user_timezone(user_id: int) -> str | None:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT timezone FROM user_timezones WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_user_timezone(user_id: int, timezone: str) -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO user_timezones (user_id, timezone) VALUES (%s, %s) ON CONFLICT(user_id) DO UPDATE SET timezone = %s",
        (user_id, timezone, timezone),
    )
    conn.commit()
    conn.close()


def get_user_time_format(user_id: int) -> str:
    """Returns '12h' or '24h' (default '24h') for the given user."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT time_format FROM user_timezones WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "24h"


def set_user_time_format(user_id: int, fmt: str) -> None:
    """Saves the user's time format preference ('12h' or '24h')."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_timezones (user_id, timezone, time_format)
        VALUES (%s, 'Etc/UTC', %s)
        ON CONFLICT(user_id) DO UPDATE SET time_format = %s
        """,
        (user_id, fmt, fmt),
    )
    conn.commit()
    conn.close()


async def timezone_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower().strip()
    if not current_lower:
        candidates = _COMMON_TIMEZONES[:25]
    else:
        all_tz = _get_all_timezones_sorted()
        starts = [tz for tz in all_tz if tz.lower().startswith(current_lower)]
        contains = [tz for tz in all_tz if current_lower in tz.lower() and not tz.lower().startswith(current_lower)]
        candidates = (starts + contains)[:25]
    return [app_commands.Choice(name=tz, value=tz) for tz in candidates]


def _format_time_in_zone(tz_name: str, time_format: str = "24h") -> str:
    """Devuelve la hora actual en la zona horaria indicada, formateada con offset UTC.

    Args:
        tz_name: nombre de zona horaria IANA (ej: 'Europe/Madrid').
        time_format: '24h' para hora militar, '12h' para AM/PM.
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    offset = now.utcoffset()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_min = abs(total_minutes)
    offset_str = f"UTC{sign}{abs_min // 60:02d}:{abs_min % 60:02d}"
    if time_format == "12h":
        time_str = now.strftime("%A, %d %B %Y  —  %I:%M:%S %p")
    else:
        time_str = now.strftime("%A, %d %B %Y  —  %H:%M:%S")
    return f"{time_str}  ({offset_str})"


@bot.tree.command(name="settimeformat", description="Elige cómo ver la hora: formato 24h (militar) o 12h (AM/PM)")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(formato="24h = hora militar  |  12h = AM/PM")
@app_commands.choices(formato=[
    app_commands.Choice(name="24h — Hora militar (ej: 14:30)", value="24h"),
    app_commands.Choice(name="12h — AM/PM (ej: 2:30 PM)", value="12h"),
])
async def cmd_settimeformat(interaction: discord.Interaction, formato: str):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id if interaction.guild else None
    is_es = get_guild_language(guild_id) == "es" if guild_id else False

    set_user_time_format(interaction.user.id, formato)

    if formato == "12h":
        label = "12h (AM/PM)"
        example = "2:30:00 PM"
    else:
        label = "24h (hora militar)"
        example = "14:30:00"

    if is_es:
        msg = (
            f"✅ Formato de hora guardado: **{label}**\n"
            f"Ejemplo: `{example}`\n\n"
            f"Los comandos `/time` y `/setmytime` usarán este formato de ahora en adelante."
        )
    else:
        msg = (
            f"✅ Time format saved: **{label}**\n"
            f"Example: `{example}`\n\n"
            f"`/time` and `/setmytime` will now use this format."
        )
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="setmytime", description="Guarda tu zona horaria para que /time muestre también tu hora local")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(timezone="Tu zona horaria (ej: Europe/Madrid, America/New_York)")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def cmd_setmytime(interaction: discord.Interaction, timezone: str):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id if interaction.guild else None
    is_es = get_guild_language(guild_id) == "es" if guild_id else False
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        err = (
            f"❌ Zona horaria no reconocida: `{timezone}`.\nUsa el autocompletado para elegir una válida."
            if is_es else
            f"❌ Unrecognized timezone: `{timezone}`.\nUse the autocomplete to pick a valid one."
        )
        await interaction.followup.send(err, ephemeral=True)
        return
    set_user_timezone(interaction.user.id, timezone)
    user_fmt = get_user_time_format(interaction.user.id)
    formatted = _format_time_in_zone(timezone, user_fmt)
    if is_es:
        msg = (
            f"✅ Tu zona horaria ha sido guardada como **{timezone}**.\n"
            f"Tu hora actual: `{formatted}`\n\n"
            f"Ahora `/time` mostrará también tu hora local automáticamente."
        )
    else:
        msg = (
            f"✅ Your timezone has been saved as **{timezone}**.\n"
            f"Your current time: `{formatted}`\n\n"
            f"From now on, `/time` will also show your local time automatically."
        )
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="time", description="Muestra la hora actual en cualquier zona horaria del mundo")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    timezone="Zona horaria a consultar (ej: Asia/Tokyo, America/New_York)",
    usuario="Compara tu hora con la de este usuario",
)
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def cmd_time(interaction: discord.Interaction, timezone: str | None = None, usuario: discord.User | None = None):
    # Defer immediately so Discord doesn't time out while we query the DB
    await interaction.response.defer()

    guild_id = interaction.guild.id if interaction.guild else None
    lang = get_guild_language(guild_id) if guild_id else "en"
    is_es = lang == "es"

    # Fetch the caller's time format preference once (used throughout this command)
    my_fmt = get_user_time_format(interaction.user.id)

    # --- Modo: comparar con otro usuario ---
    if usuario is not None:
        try:
            my_tz = get_user_timezone(interaction.user.id)
            other_tz = get_user_timezone(usuario.id)
            other_fmt = get_user_time_format(usuario.id)
        except Exception:
            logging.exception("/time usuario: error al consultar la DB")
            err = (
                "❌ Error al acceder a la base de datos. Inténtalo de nuevo más tarde."
                if is_es else
                "❌ Database error. Please try again later."
            )
            await interaction.followup.send(err, ephemeral=True)
            return

        if other_tz is None:
            if is_es:
                set_instructions = "usa el comando `/setmytime` eligiendo tu zona horaria con el autocompletado (ej: `Europe/Madrid`, `America/New_York`)"
                msg = (
                    f"⏰ {usuario.mention}, ¡{interaction.user.display_name} quiere comparar su hora con la tuya!\n"
                    f"Pero aún no tienes guardada ninguna zona horaria. Para añadirla, {set_instructions}."
                )
            else:
                set_instructions = "use the `/setmytime` command and pick your timezone from the autocomplete (e.g. `Europe/Madrid`, `America/New_York`)"
                msg = (
                    f"⏰ {usuario.mention}, {interaction.user.display_name} wants to compare their time with yours!\n"
                    f"But you haven't saved a timezone yet. To add one, {set_instructions}."
                )
            await interaction.followup.send(msg)
            return

        embed = discord.Embed(
            title="🕐  Comparación de horas" if is_es else "🕐  Time Comparison",
            color=discord.Color.blurple(),
        )

        no_tz_note = (
            "*(Sin zona horaria guardada — usa `/setmytime` para añadirla)*"
            if is_es else
            "*(No timezone saved — use `/setmytime` to add one)*"
        )
        error_note = (
            "*(Error al obtener la hora)*"
            if is_es else
            "*(Error fetching time)*"
        )

        if my_tz:
            try:
                my_time = _format_time_in_zone(my_tz, my_fmt)
                embed.add_field(
                    name=f"🏠  {interaction.user.display_name}  ({my_tz})",
                    value=f"`{my_time}`",
                    inline=False,
                )
            except Exception:
                pass
        else:
            embed.add_field(
                name=f"🏠  {interaction.user.display_name}",
                value=no_tz_note,
                inline=False,
            )

        try:
            other_time = _format_time_in_zone(other_tz, other_fmt)
            embed.add_field(
                name=f"👤  {usuario.display_name}  ({other_tz})",
                value=f"`{other_time}`",
                inline=False,
            )
        except Exception:
            embed.add_field(
                name=f"👤  {usuario.display_name}",
                value=error_note,
                inline=False,
            )

        footer = (
            "Usa /setmytime para guardar tu zona horaria • Los nombres siguen el estándar IANA"
            if is_es else
            "Use /setmytime to save your timezone • Names follow the IANA standard"
        )
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)
        return

    # --- Modo: consultar zona horaria específica ---
    if timezone is None:
        if is_es:
            msg = (
                "❌ Debes indicar una zona horaria o un usuario para comparar.\n"
                "Uso: `/time timezone:Europe/Madrid` o `/time usuario:@alguien`"
            )
        else:
            msg = (
                "❌ You must provide a timezone or a user to compare with.\n"
                "Usage: `/time timezone:Europe/Madrid` or `/time usuario:@someone`"
            )
        await interaction.followup.send(msg, ephemeral=True)
        return

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        err = (
            f"❌ Zona horaria no reconocida: `{timezone}`.\nUsa el autocompletado para elegir una válida."
            if is_es else
            f"❌ Unrecognized timezone: `{timezone}`.\nUse the autocomplete to pick a valid one."
        )
        await interaction.followup.send(err, ephemeral=True)
        return

    target_time = _format_time_in_zone(timezone, my_fmt)

    embed = discord.Embed(
        title="🌍  Hora mundial" if is_es else "🌍  World Time",
        color=discord.Color.blurple(),
    )
    embed.add_field(name=f"📍  {timezone}", value=f"`{target_time}`", inline=False)

    my_tz = get_user_timezone(interaction.user.id)
    if my_tz and my_tz != timezone:
        try:
            my_time = _format_time_in_zone(my_tz, my_fmt)
            my_label = f"🏠  Tu hora  ({my_tz})" if is_es else f"🏠  Your time  ({my_tz})"
            embed.add_field(name=my_label, value=f"`{my_time}`", inline=False)
        except Exception:
            pass

    footer = (
        "Usa /setmytime para guardar tu zona horaria • Los nombres siguen el estándar IANA"
        if is_es else
        "Use /setmytime to save your timezone • Names follow the IANA standard"
    )
    embed.set_footer(text=footer)
    await interaction.followup.send(embed=embed)


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

# Duck commands: !pato (genera pato) y !duelo (simula duelo)


@bot.command(name="pato")
async def pato(ctx: commands.Context):
    """Genera un pato con equipo aleatorio y envía su imagen."""
    async with ctx.typing():
        duck = random_duck()
        image = generate_duck(duck.equipment)
        buf = duck_to_bytes(image)
        filename = f"{duck.name.replace(' ', '_')}.png"
        equip_text = ", ".join(duck.equipment) if duck.equipment else "sin equipo"
        file = discord.File(buf, filename=filename)
    await ctx.send(content=f"**{duck.name}** — Vida: {duck.health} Ataque: {duck.attack} Defensa: {duck.defense} (Equipo: {equip_text})", file=file)


@bot.command(name="duelo")
async def duelo(ctx: commands.Context):
    """Simula un duelo entre dos patos aleatorios y muestra el resultado."""
    async with ctx.typing():
        d1 = random_duck("Pato 1")
        d2 = random_duck("Pato 2")

        # Preserve copies for images before the fight alters health
        img1 = generate_duck(d1.equipment)
        img2 = generate_duck(d2.equipment)
        buf1 = duck_to_bytes(img1)
        buf2 = duck_to_bytes(img2)

        result = fight_ducks(d1, d2, rounds=6)

        files = [discord.File(buf1, filename="pato1.png"), discord.File(buf2, filename="pato2.png")]

    # Send the fight log (in a code block) and images
    # Truncate if too long to avoid hitting message size limits
    if len(result) > 1900:
        result = result[:1900] + "\n...(truncado)"
    await ctx.send(content=f"Duelo:\n```\n{result}\n```", files=files)


@bot.command(name="howtoplay")
async def howtoplay(ctx: commands.Context):
    """Explains in English how the duck duel game works."""
    text = (
        "Duck Duel — How to play:\n"
        "- `!pato`: generates a random duck with equipment and posts its image and stats.\n"
        "- `!duelo`: simulates a short duel between two random ducks, posts both images and a fight log.\n\n"
        "Combat rules:\n"
        "- Each turn both ducks pick one action: `attack`, `defend`, or `dodge`.\n"
        "- Action relationships: `attack` beats `dodge`, `dodge` beats `defend`, `defend` beats `attack`.\n"
        "- Damage is calculated as `max(1, attacker.attack - defender.defense)`.\n\n"
        "Images are composed locally using Pillow by overlaying equipment PNGs on a base duck image.\n"
        "To customize, add assets in the `assets/` folder and update `duck_game.py`."
    )
    await ctx.send(text)


# ──────────────────────────── /translate ────────────────────────────

_TRANSLATE_LANGS = [
    ("Spanish",              "es"),
    ("English",              "en"),
    ("French",               "fr"),
    ("German",               "de"),
    ("Italian",              "it"),
    ("Portuguese",           "pt"),
    ("Dutch",                "nl"),
    ("Russian",              "ru"),
    ("Japanese",             "ja"),
    ("Korean",               "ko"),
    ("Chinese (Simplified)", "zh-CN"),
    ("Arabic",               "ar"),
    ("Hindi",                "hi"),
    ("Turkish",              "tr"),
    ("Polish",               "pl"),
    ("Swedish",              "sv"),
    ("Norwegian",            "no"),
    ("Danish",               "da"),
    ("Finnish",              "fi"),
    ("Greek",                "el"),
    ("Czech",                "cs"),
    ("Romanian",             "ro"),
    ("Ukrainian",            "uk"),
    ("Catalan",              "ca"),
]


async def _run_translation(source_text: str, target_lang: str) -> str:
    from deep_translator import GoogleTranslator

    def _do() -> str:
        return GoogleTranslator(source="auto", target=target_lang).translate(source_text)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do)


# --- Slash command: /translate text:... language:... ---

@bot.tree.command(name="translate", description="Translate text to a chosen language using Google Translate")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(
    text="Text to translate",
    language="Language to translate to",
)
@app_commands.choices(language=[
    app_commands.Choice(name=name, value=code) for name, code in _TRANSLATE_LANGS
])
async def slash_translate(
    interaction: discord.Interaction,
    text: str,
    language: app_commands.Choice[str],
):
    logging.info(f"/translate called by {interaction.user} → lang={language.value} text={text[:50]!r}")
    if not text.strip():
        await safe_reply(interaction, "The text is empty – nothing to translate.", ephemeral=True)
        return

    try:
        await interaction.response.defer(ephemeral=False)
    except Exception as e:
        logging.warning(f"/translate defer failed: {e}")
        return

    try:
        translated = await _run_translation(text.strip(), language.value)
    except Exception as e:
        logging.error(f"/translate translation error: {e}")
        await interaction.followup.send(f"Translation failed: {e}", ephemeral=True)
        return

    embed = discord.Embed(description=translated, color=discord.Color.blurple())
    embed.set_footer(text=f"Translated to {language.name} • Google Translate")
    await interaction.followup.send(embed=embed)


# --- Context menu: right-click a message → Apps → Translate ---

class TranslateLanguageView(discord.ui.View):
    """Shown after right-clicking a message. Lets the user pick a target language."""

    def __init__(self, source_text: str):
        super().__init__(timeout=60)
        self.source_text = source_text
        select = discord.ui.Select(
            placeholder="Pick a language…",
            options=[
                discord.SelectOption(label=name, value=code)
                for name, code in _TRANSLATE_LANGS
            ],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        target_code = interaction.data["values"][0]  # type: ignore[index]
        lang_name = next((n for n, c in _TRANSLATE_LANGS if c == target_code), target_code)

        await interaction.response.defer(ephemeral=True)

        try:
            translated = await _run_translation(self.source_text, target_code)
        except Exception as e:
            await interaction.followup.send(f"Translation failed: {e}", ephemeral=True)
            return

        embed = discord.Embed(description=translated, color=discord.Color.blurple())
        embed.set_footer(text=f"Translated to {lang_name} • Google Translate")
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.stop()


@bot.tree.context_menu(name="Translate")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def context_translate(interaction: discord.Interaction, message: discord.Message):
    source = message.content
    if not source or not source.strip():
        await interaction.response.send_message(
            "That message has no text to translate.", ephemeral=True
        )
        return

    view = TranslateLanguageView(source_text=source.strip())
    await interaction.response.send_message(
        "Pick the language to translate to:", view=view, ephemeral=True
    )


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
        except _discord.errors.HTTPException as e:
            if e.status == 429:
                retry_after = 60
                try:
                    retry_after = int(e.response.headers.get("Retry-After", 60))
                except Exception:
                    pass
                # Cap at 5 minutes — if Discord asks for longer, exit immediately and
                # let the host (Railway) restart the process after its own backoff.
                capped = min(retry_after, 300)
                print(f"Rate limited by Discord (429). Retry-After={retry_after}s, waiting {capped}s then exiting for fresh restart...")
                import time as _time
                _time.sleep(capped)
                raise SystemExit(0)  # exit cleanly; Railway will restart with a fresh process
            else:
                raise
