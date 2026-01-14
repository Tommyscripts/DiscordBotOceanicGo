# Furby Tournament Bot

A minimal Discord bot in Python that sends a "Furby Tournament" embed with four buttons similar to the Kirby tournament shown in the screenshots.

Features
- Slash command `/furbytournament` which posts an embed describing the tournament
- Four interactive buttons: Join Tournament, Leave Tournament, Start Tournament, Cancel Tournament
- Simple in-memory participant tracking per message (no database)

Requirements
- Python 3.10+
- discord.py 2.3+ (or next compatible version)

Setup
1. Create a virtual environment and activate it:

   python -m venv .venv
   source .venv/bin/activate

2. Install dependencies:

   pip install -r requirements.txt

3. Create a `.env` file with your bot token (see `.env.example`).

Environment variables
---------------------
Create a file named `.env` in the project root and define the following variables:

- DISCORD_TOKEN: Your bot token from the Discord Developer Portal
- GUILD_ID (optional): Your guild/server ID to register commands only there during development
- APPLICATION_ID (optional): Your application's ID (also called "Client ID")
- PUBLIC_KEY (optional): Your application's public key (used for verifying interactions in some setups)

Example `.env`:

```

Invite URL
----------
If you have `APPLICATION_ID` and `BOT_PERMISSIONS` set, the bot will print a ready-made invite URL when it starts. The format is:

```
https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot%20applications.commands&permissions=<BOT_PERMISSIONS>
```

Replace the placeholders with your `APPLICATION_ID` and `BOT_PERMISSIONS` (for example the ID you provided: `3941734153713728`).
```

4. Run the bot:

   python bot.py

Try it (local)
---------------
After creating your `.env` and installing dependencies, test the project with these steps:

1. Check Python syntax (doesn't run the bot):

```
python3 -m py_compile bot.py
```

2. Run the bot (this will connect to Discord and requires a valid token):

```
python3 bot.py
```

New features added
------------------
- Auto-mention: If anyone writes exactly (case-insensitive) the phrase "the best staff in the world" in a channel the bot can read, the bot will mention the user `Tommyhide`.
- Persistent tournament view: Tournament buttons no longer auto-expire. The lobby will remain active until someone starts or cancels the tournament.
- Public titles: When creating a tournament using `/furbytournament`, the title and embed are sent as a public message visible to everyone in the channel (not ephemeral).

Haunted House (Escape) — now with buttons
-----------------------------------------
A lightweight escape-room style mini-game is included under the `/house` command group.

- `/house create` — Crea una partida privada (solo/multi). El bot crea un canal privado.
- `/house invite` y `/house accept` — Invita y acepta jugadores (multi).
- `/house start` — Empieza la partida.

Durante la partida, el bot mostrará BOTONES de acción por turno para el jugador activo:

- Mover: Up/Down/Left/Right (solo si son válidos desde la sala actual)
- Explore (Explorar)
- Search (Buscar)
- Skip (Pasar turno)

También puedes seguir usando los comandos de acción si lo prefieres:
`/house action move <direction>`, `/house action explore`, `/house action search`.

Notas:
- El mapa se genera automáticamente (3x3) y se evita código repetitivo para crear salas.
- Las vistas (botones) son persistentes y se desactivan al avanzar el turno.

**Commands**

- **Moderation:**
   - ` /ban <user_id> [reason]` : Ban a user by ID (admin/moderation command).
   - ` /kick <user_id> [reason]` : Kick a user by ID (admin/moderation command).
   - ` /mute <user_id> [duration] [reason]` : Mute a user for a duration or assign a Muted role as fallback.
   - ` /settings_mod <command> <role>` : Configure which role can use moderation commands (ban/kick/mute). Admins only.
   - ` /settings set_staff_role <role>` : (Owner) Configure the staff role for the server.
   - ` /settings get_staff_role` : Show the configured staff role for the server.

- **House (Haunted House) game (`/house` group):**
   - ` /house create [mode] [max_players]` : Create a private House game channel (mode: solo|multi).
   - ` /house invite <user>` : Invite a user to your House game (host only).
   - ` /house accept` : Accept an invitation to a House game.
   - ` /house start` : Start the House game (host only).
   - ` /house action <action> [target]` : Perform an in-game action (search|explore|move|use).
   - ` /house move <direction>` : Shortcut to move (up/down/left/right).
   - ` /house explore` : Shortcut to explore the current room.
   - ` /house status` : Show current game status and player positions.
   - ` /house leave` : Leave the House game and revoke channel access.
   - ` /house end` : End the House game and optionally remove the private channel (host or admin).

- **Games & Tournaments:**
   - ` /wordchain [timeout]` : Start a Word Chain game lobby (players join with buttons).
   - ` /furby_tournament [title]` : Create a Furby tournament embed with Join/Leave/Start buttons.
   - ` /mm` : Quick explanation of how to play "mm".
   - ` /wheels create <text>` : Create a reaction-based wheel (users react to join).
   - ` /wheels start` : Start a wheel and pick a random winner from reactors.

- **Economy & Shop:**
   - ` /turkeys [user]` : Check your currency balance (display name/emoji configurable; defaults to Snuggles).
   - ` /give_turkeys <user> <amount>` : (Staff) Give or remove currency from a user (UI only; balances remain stored as "turkeys").
   - ` /shop list` : List available shop items for this server or global items.
   - ` /shop buy <item_id>` : Buy a shop item using the currency.
   - ` /shop add <name> <price> [role] [global]` : (Admin) Add a shop item to this server or globally.
   - ` /shop remove <item_id>` : (Admin) Remove a shop item by id.

- **Settings:**
   - ` /settings currency [name] [emoji]` : Set currency display (UI only). Use `-` to reset a field to default.

- **Scheduling:**
   - ` /schedule show` : Show today's schedule (24 slots UTC).
   - ` /schedule add <slot> <game>` : Add yourself to a numbered slot (1-24).
   - ` /schedule delete <slot>` : Remove your signup from a numbered slot (1-24).

- **Utilities & Admin:**
   - ` /resync_commands` : Force re-sync of application commands in this guild (admins only).

- **Message mod commands:**
   - `/m lock` : Lock the current text channel so that non-staff cannot send messages; preserves view permissions and saves prior overwrites.
   - `/m unlock` : Restore the channel's previous permissions saved by the lock.


How to test the mention
-----------------------
1. Run the bot (see above).
2. In any channel where the bot has read/send permissions, type exactly:

```
the best staff in the world
```

The bot will respond with a mention for `Tommyhide` (if the user exists in the server the bot will try to ping them, otherwise it will post a plain `@Tommyhide` string).

If the bot cannot start, ensure `DISCORD_TOKEN` is set and that your environment has network access. For development you can set `GUILD_ID` so commands are registered only to your server (faster sync).

Invite the bot with applications.commands and bot scopes, and give it the Send Messages and Use Application Commands permissions.

Notes
- This is a minimal example. For production, persist state in a database and add permission checks and error handling.
