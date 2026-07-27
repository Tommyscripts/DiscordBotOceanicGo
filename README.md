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
- Ruletas personalizables: cada servidor puede crear su propia ruleta con opciones personalizadas.
- Herramientas de moderación, programación de partidas y vistas interactivas.

Características principales
--------------------------
- 🦆 `!pato`: genera un pato aleatorio con equipo, imagen y estadísticas.
- ⚔️ `!duelo`: simula un combate entre dos patos y publica imágenes y log.
- 🌊 Ocean Drops: temporadas con drops automáticos, `/trade` y `/leaderboard`.
- 🧸 Teddy Wars: simulador local y comandos para publicar eventos con assets.
- 🏚️ Haunted House: escape-room cooperativo con canales privados y botones.
- 🎡 Custom Wheels: ruletas personalizables por servidor con 2-50 opciones y animación GIF.
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
- `/customwheels-settings` — Configura tu ruleta personalizada (requiere Manage Server).
- `/customwheels-spin` — Gira la ruleta y obtén un resultado aleatorio con animación.
- `/customwheels-view` — Muestra las opciones configuradas de tu ruleta.
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

Ejecutar localmente
-------------------

```bash
python3 bot.py
```

**Nota sobre sincronización de comandos:**
El bot ahora sincroniza automáticamente los comandos slash en cada inicio/redeploy a todos los servidores donde está presente. Esto significa que:
- ✅ Los comandos estarán disponibles inmediatamente después de cada redeploy en Railway
- ✅ No necesitas ejecutar `/resync_commands` manualmente después de actualizaciones
- ✅ Los comandos se sincronizan automáticamente al unirse a nuevos servidores

Si quieres usar el modo de desarrollo (sync solo a un servidor específico), define `GUILD_ID` en tu `.env`.

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


🎡 Custom Wheels — Ruletas Personalizadas
----------------------------------------

Cada servidor puede crear su propia ruleta con opciones completamente personalizadas.

### ¿Cómo funciona?

1. **Configurar** (solo administradores):
   ```
   /customwheels-settings
   ```
   - Click en "Set Number of Options" → Elige cuántas opciones (2-50)
   - Click en "Configure Options" → Nombra cada opción
   - Click en "💾 Save Wheel" → Guarda tu configuración

2. **Usar** (cualquier miembro):
   ```
   /customwheels-spin
   ```
   - Gira la ruleta y obtén un resultado aleatorio
   - Se genera un GIF animado mostrando la ruleta girando
   - El resultado se muestra en un embed elegante

3. **Ver configuración**:
   ```
   /customwheels-view
   ```
   - Muestra todas las opciones configuradas
   - Fecha de creación y última actualización

### Ejemplos de uso:
- 🎮 Decidir qué juego jugar (Minecraft, Valorant, LOL, etc.)
- 🎥 Elegir tipo de stream (Horror, Speedrun, Chill, etc.)
- 🎁 Sorteos de premios (Nitro, Gift cards, Roles, etc.)
- 🎯 Retos del servidor (Meme, Fact, Joke, Pet pic, etc.)

### Características técnicas:
- ✅ Una ruleta personalizada por servidor
- ✅ 2-50 opciones configurables
- ✅ Persistencia en base de datos (no se pierde al reiniciar)
- ✅ Animación GIF con colores distintos por opción
- ✅ Interfaz intuitiva con botones interactivos
- ✅ Disponible para todos los miembros una vez configurada

Para más detalles, consulta `docs/custom_wheels_guide.md`.


Soporte y donaciones
---------------------

El comando `/donate` muestra enlaces para apoyar el hosting y los assets.
PayPal del autor (tal como aparece en el bot): https://paypal.me/Javicez

Notas finales — Lore friki
------------------------

Oceanic es la prueba viviente de que un pato con brújula propia puede dirigir una flota. Si quieres que le añadamos insignias por colecciones completas, integración web o más minijuegos, dime y lo añadimos al mapa de navegación.

— Capitán Pato 🦆
