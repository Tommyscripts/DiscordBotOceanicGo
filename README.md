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
