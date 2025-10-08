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
        synced = await bot.tree.sync(guild=discord.Object(id=int(GUILD_ID))) if GUILD_ID else await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
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


@bot.tree.group(name="schedule", description="Show or add schedule signups", invoke_without_command=True)
async def schedule_group(interaction: discord.Interaction):
    # default to show
    await show_schedule(interaction)


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
