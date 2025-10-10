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

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = wordchain_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("No active lobby.", ephemeral=True)
            return
        removed = game.remove_player(interaction.user.id)
        if removed:
            await interaction.response.send_message("You left the lobby.", ephemeral=True)
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
        # begin turn loop
        asyncio.create_task(run_wordchain_game(game))


async def run_wordchain_game(game: WordChainGame):
    channel = game.channel
    await channel.send("Word Chain: game is live! First player will be chosen from lobby.")
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

    # announce winner
    survivors = game.alive_players()
    if survivors:
        winner = survivors[0]
        await channel.send(f"Game over! The winner is <@{winner}> 🎉")
    else:
        await channel.send("Game over! No winners — everyone lost their lives.")
    # cleanup
    try:
        del wordchain_games[channel.id]
    except KeyError:
        pass

# Slash command to create lobby and start game
@bot.tree.command(name="wordchain", description="Start a Word Chain game (join via buttons, start when ready)")
@app_commands.describe(timeout="Turn timeout in seconds (10-30). Default 15")
async def slash_wordchain(interaction: discord.Interaction, timeout: int = 15):
    # create a lobby message with Join/Leave/Start buttons
    if interaction.channel is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command must be used in a text channel.", ephemeral=True)
        return
    channel = interaction.channel
    if channel.id in wordchain_games:
        await interaction.response.send_message("There's already an active lobby or game in this channel.", ephemeral=True)
        return
    timeout = max(5, min(30, timeout))
    game = WordChainGame(channel=channel, starter=None, turn_timeout=timeout)
    wordchain_games[channel.id] = game
    view = WordChainView(channel_id=channel.id)
    # add host as first player automatically
    game.add_player(interaction.user.id)
    await interaction.response.send_message(f"Word Chain lobby created by {interaction.user.mention}! Click Join to participate. Turn timeout: {timeout}s. Host auto-joined.", view=view)

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
DB_PATH = os.path.join(os.path.dirname(__file__), "furby_stats.db")

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
        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        meta = tournaments_meta.get(msg_id, {})
        maxp = meta.get("max_participants", 50)
        if interaction.user.id in participants:
            await interaction.response.send_message("you're in.", ephemeral=True)
            return
        if len(participants) >= maxp:
            await interaction.response.send_message(f"Tournament is fulle ({maxp} participants). you can't join.", ephemeral=True)
            return
        participants.add(interaction.user.id)
        # build a small participant preview
        preview = "\n".join([f"<@{uid}>" for uid in list(participants)[:20]])
        await interaction.response.send_message(f"{interaction.user.mention} just joined tournament.\nParticipantes: {len(participants)}/{maxp}\n\n{preview}", ephemeral=True)
        await update_tournament_message(interaction.message)

    @discord.ui.button(label="Leave Tournament", style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        if interaction.user.id not in participants:
            await interaction.response.send_message("No estás en el torneo.", ephemeral=True)
            return
        participants.remove(interaction.user.id)
        meta = tournaments_meta.get(msg_id, {})
        maxp = meta.get("max_participants", 50)
        preview = "\n".join([f"<@{uid}>" for uid in list(participants)[:20]])
        await interaction.response.send_message(f"{interaction.user.mention} left tournament.\nParticipants: {len(participants)}/{maxp}\n\n{preview if preview else 'No hay participantes.'}", ephemeral=True)
        await update_tournament_message(interaction.message)

    @discord.ui.button(label="Start Tournament", style=discord.ButtonStyle.primary, emoji="▶️")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only host or users with manage_guild can start
        if self.host and interaction.user != self.host and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Only the host or a manager can start the tournament.", ephemeral=True)
            return
        msg_id = interaction.message.id
        participants = tournaments.get(msg_id, set())
        if len(participants) < 2:
            await interaction.response.send_message("Need at least 2 furbys to start.", ephemeral=True)
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
            await interaction.response.send_message("Only the host or a manager can cancel the tournament.", ephemeral=True)
            return
        msg_id = interaction.message.id
        tournaments.pop(msg_id, None)
        await interaction.response.send_message("Tournament cancelled.", ephemeral=False)
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.Forbidden:
            print(f"Warning: cannot edit view for message {interaction.message.id} - missing permissions.")
        except discord.HTTPException as e:
            print(f"Warning: failed to edit view for message {interaction.message.id}: {e}")

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
        participants_text = "No furbys joined yet."

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
    embed = discord.Embed(title="Wheels", description=text, color=0x22AAFF)
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
        await interaction.response.send_message("No wheel found hosted by you in this channel.", ephemeral=True)
        return

    msg_id, message_obj, meta = candidate
    participants = list(wheels.get(msg_id, set()))
    if not participants:
        await interaction.response.send_message("No participants have joined the wheel.", ephemeral=True)
        return

    # Acknowledge start and generate a graphical wheel image
    await interaction.response.send_message("Spinning the wheel... 🎡", ephemeral=False)

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
            # adaptive font sizing
            try:
                base_font_size = max(12, int(180 / max(8, num)))
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
                max_len = 18
                if len(text) > max_len:
                    text = text[:max_len-1] + "…"
                tw, th = ldraw.textsize(text, font=font)
                # draw centered
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
            wtw, wth = fdraw.textsize(winner_text, font=font_sm)
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
            await channel.send("Spinning: " + names_mention)
    except Exception:
        pass

    # short pause to simulate spinning (approx 5 seconds)
    await asyncio.sleep(5)

    # choose winner among full participants (not only displayed slice subset)
    winner_id = random.choice(participants)
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

    # cleanup wheel data
    wheels.pop(msg_id, None)
    wheels_meta.pop(msg_id, None)

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

@bot.tree.command(name="furbytournament", description="Create a Furby Tournament embed")
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
        # compute unix ts for today at hour:00 UTC
        struct = time.strptime(f"{today} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        ts = int(time.mktime(struct))
        # Discord will display the timestamp according to the viewer's local timezone when using <t:...:t>
        time_token = f"<t:{ts}:t>"
        entries = slots.get(hour) or []
        if entries:
            entry_text = ", ".join([f"<@{uid}> ({game})" for uid, game in entries])
        else:
            entry_text = "(empty)"
        # Format hour to 12-hour AM/PM for display label
        label = time.strftime("%I %p", time.strptime(f"{hour:02d}", "%H"))
        # remove leading zero from hour label
        if label.startswith("0"):
            label = label[1:]
        desc_lines.append(f"**{label}** — {time_token} : {entry_text}")

    embed = discord.Embed(title="Schedule (24h)", description="\n".join(desc_lines), color=0x00BFFF)
    await interaction.response.send_message(embed=embed, ephemeral=False)


@schedule_group.command(name="add", description="Add yourself to a slot")
@app_commands.describe(time="Hour in 0-23 (server local 24h)", game="Game or note to add")
async def add_schedule(interaction: discord.Interaction, time: int, game: str):
    # normalize time to 0-23
    if time < 0 or time > 23:
        await interaction.response.send_message("Please provide an hour between 0 and 23.", ephemeral=True)
        return

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

    await interaction.response.send_message(f"Added you to {time:02d}:00 UTC for '{game}'. Use `/schedule show` to view.", ephemeral=True)


# register the group with the bot's command tree
try:
    bot.tree.add_command(schedule_group)
except Exception:
    # in case adding twice or running in reload scenarios
    pass


@bot.tree.command(name="resync", description="Force re-sync application commands in this guild (admins only)")
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
