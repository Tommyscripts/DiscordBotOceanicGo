🌊 Oceanic — Discord Bot (The Geeky Fleet of the Abyss)

```
        _~_                 _~_
     _~)   (_~_           _~)   (_~_
    (___     ___)  OCEANIC (___     ___)
       /'---'\               /'---'\  
      /  🐙 🦆 🧸 \   Navigate, collect and fight  /  🐚  🐬  \
```

Welcome to the marine sanctuary where ducks are heroes, teddy bears lay siege, and shells shine brighter than your notifications. Oceanic is a Discord bot designed to take your server on an oceanic adventure: mini-games, seasonal drops, economy, and moderation tools — all with a geeky vibe.

What does Oceanic do? — Quick summary:
- Games: epic duck generator, duels, Teddy Wars, and House (escape room).
- Seasonal drops with collectibles, trading, and leaderboard.
- Light economy and social shop (Snuggles / turkeys).
- Customizable wheels: each server can create their own custom wheel with personalized options.
- Moderation tools, match scheduling, and interactive views.

Main Features
--------------------------
- 🦆 `!pato`: generates a random duck with equipment, image, and stats.
- ⚔️ `!duelo`: simulates a battle between two ducks and publishes images and log.
- 🌊 Ocean Drops: seasons with automatic drops, `/trade` and `/leaderboard`.
- 🧸 Teddy Wars: local simulator and commands to publish events with assets.
- 🏚️ Haunted House: cooperative escape-room with private channels and buttons.
- 🎡 Custom Wheels: customizable wheels per server with 2-50 options and GIF animation.
- ⏲️ `/schedule`: schedule system with time zone visualization for viewers.
- 🖼️ Local image generation using Pillow (assets in `assets/` and `teddy_wars/`).

Featured Commands
-------------------

Text commands (prefix `!`):
- `!pato` — Generates and sends the image and stats of a random duck.
- `!duelo` — Simulates a duel between two ducks and shows the result.
- `!howtoplay` — Explains the duck duel rules.

Slash commands (/):
- `/ocean_drop [mode=random|channel]` — Launch a manual drop.
- `/ocean_active <role> [min_minutes max_minutes]` — Activate automatic drops (staff).
- `/collection` and `/view_collection <member>` — View collectibles.
- `/trade <member> <offer> <request>` — Propose a trade.
- `/leaderboard` — Top collectors of the season.
- `/house` — Command group for Haunted House (create, invite, start, action...)
- `/schedule show|add|delete` — Schedule management and bookings.
- `/customwheels-settings` — Configure your custom wheel (requires Manage Server).
- `/customwheels-spin` — Spin the wheel and get a random result with animation.
- `/customwheels-view` — Shows your wheel's configured options.
- `/resync_commands` — Force re-sync of commands (admins).
- `/m lock` / `/m unlock` — Lock/unlock channel quickly.

Quick Installation
------------------

Requirements: Python 3.10+. For persistence, a Postgres database and `asyncpg`.

```bash
git clone <your-repo>
cd DiscordBotOceanicGo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure environment variables in a `.env` file in the root:

```
DISCORD_TOKEN=your_token_here
GUILD_ID=123456789012345678   # optional (command registration in dev)
APPLICATION_ID=123456789012345678  # optional
PUBLIC_KEY=...
BOT_PERMISSIONS=3941734153713728
DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

Run Locally
-------------------

```bash
python3 bot.py
```

**Note about command synchronization:**
The bot now automatically syncs slash commands on every startup/redeploy to all servers where it's present. This means:
- ✅ Commands will be available immediately after each Railway redeploy
- ✅ You don't need to manually run `/resync_commands` after updates
- ✅ Commands are automatically synced when joining new servers

If you want to use development mode (sync only to a specific server), define `GUILD_ID` in your `.env`.

Teddy Wars simulator (doesn't need Discord):

```bash
python3 -m oceanic_bot.games.teddy_war_sim -n 6
```

Generate/update duck assets:

```bash
python assets/generate_duck_assets.py
```

Main Dependencies
-----------------------
- `discord.py` (2.3+)
- `python-dotenv` (for `.env`)
- `Pillow` (image composition)
- `asyncpg` (optional Postgres)


🎡 Custom Wheels — Personalized Roulettes
----------------------------------------

Each server can create their own wheel with completely customized options.

### How does it work?

1. **Setup** (administrators only):
   ```
   /customwheels-settings
   ```
   - Click "Set Number of Options" → Choose how many options (2-50)
   - Click "Configure Options" → Name each option
   - Click "💾 Save Wheel" → Save your configuration

2. **Use** (any member):
   ```
   /customwheels-spin
   ```
   - Spin the wheel and get a random result
   - An animated GIF is generated showing the wheel spinning
   - The result is shown in an elegant embed

3. **View configuration**:
   ```
   /customwheels-view
   ```
   - Shows all configured options
   - Creation date and last update

### Usage examples:
- 🎮 Decide what game to play (Minecraft, Valorant, LOL, etc.)
- 🎥 Choose stream type (Horror, Speedrun, Chill, etc.)
- 🎁 Prize giveaways (Nitro, Gift cards, Roles, etc.)
- 🎯 Server challenges (Meme, Fact, Joke, Pet pic, etc.)

### Technical features:
- ✅ One custom wheel per server
- ✅ 2-50 configurable options
- ✅ Database persistence (won't be lost on restart)
- ✅ GIF animation with distinct colors per option
- ✅ Intuitive interface with interactive buttons
- ✅ Available to all members once configured

For more details, see `docs/custom_wheels_guide.md`.


Support and Donations
---------------------

The `/donate` command shows links to support hosting and assets.
Author's PayPal (as shown in the bot): https://paypal.me/Javicez

Final Notes — Geeky Lore
------------------------

Oceanic is living proof that a duck with its own compass can lead a fleet. If you want us to add badges for complete collections, web integration, or more mini-games, let me know and we'll add it to the navigation map.

— Captain Duck 🦆
