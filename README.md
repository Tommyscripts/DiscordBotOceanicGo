🌊 Oceanic — Bot de Discord (La Flota Friki del Abismo)

```
        _~_                 _~_
     _~)   (_~_           _~)   (_~_
    (___     ___)  OCEANIC (___     ___)
       /'---'\               /'---'\  
      /  🐙 🦆 🧸 \   Navega, colecciona y lucha  /  🐚  🐬  \
```

Bienvenido al santuario marino donde los patos son héroes, los peluches asedian y las conchas brillan más que tus notificaciones. Oceanic es un bot de Discord diseñado para llevar a tu servidor a una aventura oceánica: minijuegos, drops estacionales, economía y herramientas de moderación — todo con mucho rollo friki.

¿Qué hace Oceanic? — Resumen rápido:
- Juegos: generador de patos épicos, duelos, Teddy Wars y House (escape).
- Drops estacionales con coleccionables, comercio y leaderboard.
- Economía ligera y tienda social (Snuggles / turkeys).
- Herramientas de moderación, programación de partidas y vistas interactivas.

Características principales
--------------------------
- 🦆 `!pato`: genera un pato aleatorio con equipo, imagen y estadísticas.
- ⚔️ `!duelo`: simula un combate entre dos patos y publica imágenes y log.
- 🌊 Ocean Drops: temporadas con drops automáticos, `/trade` y `/leaderboard`.
- 🧸 Teddy Wars: simulador local y comandos para publicar eventos con assets.
- 🏚️ Haunted House: escape-room cooperativo con canales privados y botones.
- ⏲️ `/schedule`: sistema de horarios con visualización por zona horaria del espectador.
- 🖼️ Generación de imágenes local usando Pillow (assets en `assets/` y `teddy_wars/`).

Comandos destacados
-------------------

Comandos de texto (prefijo `!`):
- `!pato` — Genera y envía la imagen y stats de un pato aleatorio.
- `!duelo` — Simula un duelo entre dos patos y muestra el resultado.
- `!howtoplay` — Explica (en inglés) las reglas del duelo de patos.

Comandos de barra (/):
- `/ocean_drop [modo=random|channel]` — Lanzar un drop manual.
- `/ocean_active <rol> [min_minutos max_minutos]` — Activar drops automáticos (staff).
- `/collection` y `/view_collection <miembro>` — Ver coleccionables.
- `/trade <miembro> <oferta> <peticion>` — Proponer un trade.
- `/leaderboard` — Top collectors de la temporada.
- `/house` — Grupo de comandos para la Haunted House (create, invite, start, action...)
- `/schedule show|add|delete` — Gestión de horarios y reservas.
- `/resync_commands` — Forzar re-sync de comandos (admins).
- `/m lock` / `/m unlock` — Bloquear/desbloquear canal rápidamente.

Instalación rápida
------------------

Requisitos: Python 3.10+. Para persistencia, una base Postgres y `asyncpg`.

```bash
git clone <tu-repo>
cd DiscordBotOceanicGo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configura variables de entorno en un archivo `.env` en la raíz:

```
DISCORD_TOKEN=tu_token_aqui
GUILD_ID=123456789012345678   # opcional (registro de comandos en dev)
APPLICATION_ID=123456789012345678  # opcional
PUBLIC_KEY=...
BOT_PERMISSIONS=3941734153713728
```

Ejecutar localmente
-------------------

```bash
python3 bot.py
```

Simulador Teddy Wars (no necesita Discord):

```bash
python3 -m oceanic_bot.games.teddy_war_sim -n 6
```

Generar/actualizar assets de pato:

```bash
python assets/generate_duck_assets.py
```

Dependencias principales
-----------------------
- `discord.py` (2.3+)
- `python-dotenv` (para `.env`)
- `Pillow` (composición de imágenes)
- `asyncpg` (Postgres opcional)

Arquitectura (rápido)
--------------------

```mermaid
graph LR
  Discord[Discord] -->|Interactions| Bot[bot.py]
  Bot -->|DB (asyncpg)| Postgres[(Postgres)]
  Bot -->|Assets| Assets[assets/ , teddy_wars/]
  Bot -->|Image gen| Pillow
```

Contribuir
---------

- Haz fork → crea una rama → PR.
- Añade tests si cambias lógica compleja (ver `tools/`).
- Si aportas assets, mantén tamaños razonables y transparencia en PNG.

Soporte y donaciones
---------------------

El comando `/donate` muestra enlaces para apoyar el hosting y los assets.
PayPal del autor (tal como aparece en el bot): https://paypal.me/Javicez

Notas finales — Lore friki
------------------------

Oceanic es la prueba viviente de que un pato con brújula propia puede dirigir una flota. Si quieres que le añadamos insignias por colecciones completas, integración web o más minijuegos, dime y lo añadimos al mapa de navegación.

— Capitán Pato 🦆
