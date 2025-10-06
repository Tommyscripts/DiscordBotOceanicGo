import os
import asyncio
from typing import List, Set

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import sqlite3
import time

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
APPLICATION_ID = os.getenv("APPLICATION_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_PERMISSIONS = os.getenv("BOT_PERMISSIONS", "3941734153713728")

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
    conn.commit()
    conn.close()

init_db()

class TournamentView(discord.ui.View):
    def __init__(self, host: discord.Member | None = None, timeout: int = 60 * 60):
        super().__init__(timeout=timeout)
        self.host = host

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # allow everyone to press buttons; you can add checks here
        return True

    @discord.ui.button(label="Join Tournament", style=discord.ButtonStyle.success, emoji="🏆")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        if interaction.user.id in participants:
            await interaction.response.send_message("You're already joined.", ephemeral=True)
            return
        participants.add(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.mention} joined the Furby tournament!", ephemeral=True)
        await update_tournament_message(interaction.message)

    @discord.ui.button(label="Leave Tournament", style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id
        participants = tournaments.setdefault(msg_id, set())
        if interaction.user.id not in participants:
            await interaction.response.send_message("You're not in the tournament.", ephemeral=True)
            return
        participants.remove(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.mention} left the Furby tournament.", ephemeral=True)
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

        # Simulate selecting a winner randomly from participants
        import random

        winner_id = random.choice(list(participants))
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

        # Notify channel and update embed with winner, stats and duration
        await interaction.response.send_message(f"Tournament finished! Winner: {winner_mention}. Host: {host_mention}")

        # Optionally disable buttons after start
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

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
        await interaction.message.edit(embed=new_embed)

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
        await interaction.message.edit(view=self)

async def update_tournament_message(message: discord.Message):
    """Update the embed of the tournament message to reflect current participants."""
    msg_id = message.id
    participants = tournaments.get(msg_id, set())
    embed = message.embeds[0]
    # Rebuild the description with updated participant count and list
    base_description = embed.description.split("\n\n", 1)[0]
    # create a small participants list
    if participants:
        part_lines = []
        for uid in list(participants)[:20]:
            part_lines.append(f"<@{uid}>")
        participants_text = "\n".join(part_lines)
    else:
        participants_text = "No furbys joined yet."

    new_description = f"{base_description}\n\nParticipants ({len(participants)}):\n{participants_text}" 
    new_embed = embed.copy()
    new_embed.description = new_description
    await message.edit(embed=new_embed)

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
        "• Maximum 75 participants allowed\n\n"
        "⚡ Revival System ⚡\n"
        "• Eliminated Furbys may get a second chance!\n"
        "• Revival checks occur at specific rounds\n"
        "• There's a 60% chance of revival occurring\n"
        "• Only a limited number of Furbys can be revived\n"
        "• Each Furby can only be revived once per tournament\n\n"
        "Lobby Timeout\n"
        "This lobby will close in 7 minutes\n\n"
        "Today at "
    )
    embed.description = description + discord.utils.format_dt(discord.utils.utcnow(), style="t")
    embed.set_footer(text=f"Host: {host.display_name}")

    view = TournamentView(host=host)
    msg = await interaction.response.send_message(embed=embed, view=view)
    # interaction.response.send_message returns None when deferred; fetch the message
    # so instead we use followup to get the message object
    sent = await interaction.original_response()
    tournaments[sent.id] = set()

if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN not set in environment. Copy .env.example to .env and set your token.")
        raise SystemExit(1)
    bot.run(TOKEN)
