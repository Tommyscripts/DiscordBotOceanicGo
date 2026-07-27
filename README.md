# 🌊 Oceanic — Bot de Discord

```
        _~_                 _~_
     _~)   (_~_           _~)   (_~_
    (___     ___)  OCEANIC (___     ___)
       /'---'\               /'---'\
      /  🐙 🦆 🧸 \   Navega, colecciona y lucha  /  🐚  🐬  \
```

**Oceanic** es un bot de Discord con minijuegos, coleccionables, economía, torneos de peluches, ruletas y herramientas de moderación. Todo en un solo bot, fácil de instalar.

---

## 📋 Índice

1. [¿Qué puede hacer Oceanic?](#-qué-puede-hacer-oceanic)
2. [Instalación rápida](#-instalación-rápida)
3. [Variables de entorno](#-variables-de-entorno)
4. [Comandos — Juegos](#-comandos--juegos)
5. [Comandos — Ocean Drops (Coleccionables)](#-comandos--ocean-drops-coleccionables)
6. [Comandos — Economía y Tienda](#-comandos--economía-y-tienda)
7. [Comandos — Ruletas](#-comandos--ruletas)
8. [Comandos — Horarios](#-comandos--horarios)
9. [Comandos — Moderación](#-comandos--moderación)
10. [Comandos — Ajustes del servidor](#-comandos--ajustes-del-servidor)
11. [Comandos — Utilidades generales](#-comandos--utilidades-generales)
12. [Monopoly GO — Links automáticos](#-monopoly-go--links-automáticos)
13. [Comandos — Hora mundial](#-comandos--hora-mundial)
14. [Herramientas de desarrollo](#-herramientas-de-desarrollo)
15. [Despliegue en Railway](#-despliegue-en-railway)

---

## 🎮 ¿Qué puede hacer Oceanic?

| Categoría | Descripción |
|---|---|
| 🦆 **Patos** | Genera patos épicos con equipo aleatorio e imágenes |
| ⚔️ **Duelos** | Simula combates entre patos con imágenes y log de batalla |
| 🧸 **Teddy Wars** | Torneo de peluches con imágenes y narración dramática |
| 🧸 **Team Teddy War** | Torneo por equipos de 2 jugadores |
| 🏚️ **Haunted House** | Escape room cooperativo con canales privados y botones |
| 🔤 **Word Chain** | Cadena de palabras multijugador con vidas |
| 🌊 **Ocean Drops** | Coleccionables estacionales, trading y leaderboard |
| 🎡 **Custom Wheels** | Ruleta personalizable por servidor (animación GIF) |
| 🎡 **Wheels** | Ruleta de reacción para sorteos rápidos |
| 💰 **Economía** | Moneda Snuggles, tienda y premios por ganar juegos |
| 📅 **Schedule** | Sistema de horarios con zonas horarias personalizadas |
| 🛡️ **Moderación** | Ban, kick, mute, lock/unlock de canales |
| 🎲 **Monopoly GO** | Publicación automática de links de recompensas |
| 🌐 **Traducciones** | Interfaz en inglés o español por servidor |

---

## 🚀 Instalación rápida

**Requisitos:** Python 3.10+, PostgreSQL, Git.

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd DiscordBotOceanicGo

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate      # Linux / Mac
# .venv\Scripts\activate       # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Crear archivo .env con tu configuración
cp .env.example .env           # si existe, sino créalo manualmente

# 5. Arrancar el bot
python3 bot.py
```

---

## 🔑 Variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
# Obligatorio
DISCORD_TOKEN=tu_token_de_discord_aqui
DATABASE_URL=postgresql://usuario:contraseña@host:5432/nombre_db

# Opcionales
GUILD_ID=123456789012345678        # Si se define, los comandos solo se sincronizan a este servidor (modo dev)
APPLICATION_ID=123456789012345678
PUBLIC_KEY=tu_clave_publica
BOT_PERMISSIONS=3941734153713728

# Auto-resync de comandos (opcional)
AUTO_RESYNC=true                   # Activa el loop de resync automático
AUTO_RESYNC_INTERVAL=300           # Intervalo en segundos (default: 300)
```

> **Nota:** El bot sincroniza automáticamente los comandos slash en cada arranque a todos los servidores donde está presente. No necesitas `/resync_commands` tras cada actualización.

---

## 🎮 Comandos — Juegos

### 🦆 Patos (`!`)

| Comando | Descripción |
|---|---|
| `!pato` | Genera un pato aleatorio con equipo (casco, espada, escudo) y muestra su imagen y estadísticas |
| `!duelo` | Simula un duelo entre dos patos aleatorios. Muestra las imágenes y el resultado por rondas |
| `!howtoplay` | Explica las reglas del duelo de patos |

**Mecánica de combate:**
- Acciones por turno: `attack`, `defend`, `dodge`
- `attack` vence a `dodge` · `dodge` vence a `defend` · `defend` vence a `attack`
- Daño: `max(1, ataque_atacante − defensa_defensor)`

---

### 🧸 Teddy Wars (`/`)

Torneo donde los peluches se enfrentan con imágenes y narración épica.

| Comando | Descripción |
|---|---|
| `/teddy_war [title]` | Crea un torneo Teddy War. Se abre un embed con botones para unirse |
| `/teamteddy [title]` | Crea un torneo por equipos de 2 jugadores (hasta 16 equipos) |
| `/jointeamteddy` | Muestra un menú con botones para elegir equipo en el torneo activo del canal |

**Cómo funciona:**
1. El host ejecuta `/teddy_war` o `/teamteddy`
2. Los participantes hacen clic en **Join Tournament** (o `/jointeamteddy`)
3. El host pulsa **Start Tournament** cuando hay al menos 2 participantes
4. El bot narra la batalla con imágenes de peluches, ataques, revividas y taunts
5. El ganador recibe Snuggles y hay un 10% de probabilidad de ganar un coleccionable de Ocean Drop

> **Team Teddy War:** cada equipo necesita exactamente 2 jugadores. Se necesitan mínimo 2 equipos completos para comenzar. El ganador es el último equipo en pie.

---

### 🏚️ Haunted House (`/house`)

Escape room cooperativo con canales privados e interacción por botones.

| Comando | Descripción |
|---|---|
| `/house create [mode] [max_players]` | Crea una partida. Crea un canal privado automáticamente. `mode`: `solo` o `multi` |
| `/house howto` | Explica cómo jugar |
| `/house invite <usuario>` | El host invita a un usuario (solo en modo multi) |
| `/house accept` | Acepta la invitación y accede al canal privado |
| `/house start` | El host inicia la partida cuando hay jugadores suficientes |
| `/house action <acción> [objetivo]` | Ejecuta una acción en tu turno |
| `/house move <dirección>` | Atajo para moverse (up / down / left / right) |
| `/house explore` | Atajo para explorar la habitación actual |
| `/house status` | Muestra el estado de la partida (HP, posición, inventario) |
| `/house leave` | Abandona la partida |
| `/house end` | El host termina la partida y elimina el canal privado |

**Acciones disponibles:** `search` (busca objetos), `explore` (describe la habitación), `move <dirección>`, `use <objeto>`

**Objetivo:** Encuentra la **llave antigua** con `search`, lleva al **exit room (0,0)** y usa la llave para escapar.

---

### 🔤 Word Chain (`/wordchain`)

| Comando | Descripción |
|---|---|
| `/wordchain [timeout]` | Crea un lobby de Cadena de Palabras. `timeout`: segundos por turno (5–30, default 15) |

**Cómo jugar:**
1. El host crea el lobby con `/wordchain`
2. Los jugadores hacen clic en **Join** (al menos 2)
3. El host pulsa **Start**
4. Cada jugador debe decir una palabra que empiece por la última letra de la palabra anterior
5. Si fallas o te quedas sin tiempo, pierdes 1 vida (tienes 3). El último con vidas gana
6. El ganador recibe Snuggles (2× el número de participantes)

---

## 🌊 Comandos — Ocean Drops (Coleccionables)

Sistema de drops estacionales donde los usuarios compiten por coleccionar todos los ítems.

**Coleccionables de verano:** 🐚 Ocean Shell · 🌺 Hibiscus Charm · 🥥 Golden Coconut · ☀️ Sunset Crystal · 🏄 Surf Token · 🌊 Wave Fragment

| Comando | Descripción |
|---|---|
| `/ocean_active <rol> [min] [max]` | **(Staff)** Activa drops automáticos. `rol` define los canales visibles para ese rol. `min`/`max`: intervalo en minutos |
| `/ocean_drop [mode]` | **(Staff)** Lanza un drop manual. `mode`: `random` (canal aleatorio) o `channel` (canal actual) |
| `/collection` | Muestra tu colección de la temporada actual |
| `/view_collection <miembro>` | Muestra la colección de otro usuario |
| `/trade <miembro> <oferta> <peticion>` | Propone un intercambio de coleccionables con otro usuario |
| `/leaderboard` | Muestra el top de coleccionistas de la temporada |
| `/give_item <miembro> <ítem>` | **(Staff)** Da un ítem a un usuario directamente |
| `/remove_item <miembro> <ítem>` | **(Staff)** Elimina un ítem de la colección de un usuario |

**Recompensa especial:** Al completar la colección completa se otorga un rol especial.

---

## 💰 Comandos — Economía y Tienda

La moneda del bot se llama **Snuggles** 🦃 (nombre y emoji personalizables por servidor).

| Comando | Descripción |
|---|---|
| `/snuggles [usuario]` | Consulta el saldo de Snuggles. Si se especifica `usuario`, muestra el suyo |
| `/give_snuggles <usuario> <cantidad>` | **(Staff)** Da o quita Snuggles a un usuario (admite negativos) |
| `/rename_currency [name] [emoji]` | **(Staff)** Cambia el nombre y/o emoji de la moneda (solo visual, el saldo no cambia). Usa `-` para resetear |
| `/shop list` | Lista los ítems disponibles en la tienda del servidor |
| `/shop buy <id>` | Compra un ítem de la tienda usando Snuggles |
| `/shop add <nombre> <precio> [rol] [global_item]` | **(Admin)** Añade un ítem a la tienda. Si tiene `rol`, se asigna automáticamente al comprar |
| `/shop remove <id>` | **(Admin)** Elimina un ítem de la tienda |

**¿Cómo ganar Snuggles?**
- Ganar Word Chain → 2 × nº de participantes
- Ganar una Wheel → 2 × nº de participantes
- Ganar Teddy War → 2 × nº de participantes
- Ganar Team Teddy War → 3 × nº de participantes por miembro ganador

---

## 🎡 Comandos — Ruletas

### Ruleta personalizada (Custom Wheels)

Cada servidor puede configurar su propia ruleta con hasta 50 opciones y animación GIF.

| Comando | Descripción |
|---|---|
| `/customwheels-settings` | Abre el menú de configuración de la ruleta (requiere **Manage Server**) |
| `/customwheels-spin` | Gira la ruleta y muestra el resultado animado con GIF |
| `/customwheels-view` | Muestra las opciones configuradas actualmente |

### Ruleta de reacción (Wheels)

Ideal para sorteos rápidos entre usuarios que reaccionan a un mensaje.

| Comando | Descripción |
|---|---|
| `/wheels create <texto>` | Crea un post de ruleta. El bot reacciona con 🎡 y los usuarios que reaccionen también entran |
| `/wheels start` | El host inicia la ruleta. Elige un ganador aleatorio, genera un GIF animado y entrega Snuggles |

---

## 📅 Comandos — Horarios

Sistema de horarios con soporte completo de zonas horarias. Cada usuario ve los horarios convertidos a **su** hora local.

| Comando | Descripción |
|---|---|
| `/schedule show` | Muestra el horario de hoy con 48 franjas de 30 minutos en tu zona horaria |
| `/schedule add [game]` | Añade tu nombre al horario. Muestra botones interactivos para elegir hora y minutos |
| `/schedule delete` | Elimina tu inscripción. Muestra botones interactivos para elegir la franja a borrar |
| `/setmytime <zona>` | Guarda tu zona horaria (ej: `Europe/Madrid`, `America/New_York`) |
| `/settimeformat <formato>` | Elige el formato de hora: `24h` o `12h` (AM/PM) |

> **Ejemplo de uso:** Si estás en Madrid (`Europe/Madrid`) y añades las 20:00, un usuario en Nueva York verá las 14:00 automáticamente.

---

## 🛡️ Comandos — Moderación

### Comandos slash

| Comando | Permisos | Descripción |
|---|---|---|
| `/ban <user_id> [reason]` | Rol de moderación o Admin | Banea a un usuario por ID. Acepta menciones o IDs |
| `/kick <user_id> [reason]` | Rol de moderación o Admin | Expulsa a un usuario del servidor |
| `/mute <user_id> [duration] [reason]` | Rol de moderación o Admin | Silencia a un usuario. Duración: `10m`, `2h`, `1d`. Sin duración = permanente |
| `/m lock` | Staff | Bloquea el canal actual para que solo el staff pueda escribir |
| `/m unlock` | Staff | Desbloquea el canal y restaura los permisos anteriores |
| `/settings_mod <comando> [rol]` | Admin/Owner | Configura qué rol puede usar ban/kick/mute |

### Comandos de texto (mensaje directo)

| Comando | Descripción |
|---|---|
| `/m lock` (como mensaje) | Bloquea el canal actual (solo staff) |
| `/m unlock` (como mensaje) | Desbloquea el canal actual (solo staff) |

---

## ⚙️ Comandos — Ajustes del servidor

| Comando | Permisos | Descripción |
|---|---|---|
| `/settings menu` | Manage Server | Abre un menú interactivo de configuración |
| `/settings currency [name] [emoji] [command_name]` | Manage Server | Configura nombre, emoji y nombre del comando de saldo |
| `/settings set_staff_role <roles>` | Owner | Define los roles de staff (separados por comas o espacios) |
| `/settings add_staff_role <rol>` | Owner | Añade un rol a la lista de staff |
| `/settings remove_staff_role <rol>` | Owner | Elimina un rol de la lista de staff |
| `/settings get_staff_role` | Cualquiera | Muestra los roles de staff configurados |
| `/settings show` | Cualquiera | Muestra todos los ajustes principales del servidor |
| `/settings mod_role <comando> [rol]` | Owner/Admin | Configura el rol para ban/kick/mute individualmente |
| `/settings language <en\|es>` | Manage Server | Cambia el idioma de las descripciones de comandos |

---

## � Apoya el bot — `/donate`

Oceanic corre en servidores de pago. Si el bot te divierte o le da vida a tu servidor, puedes ayudar a mantenerlo en marcha con una donación:

```
/donate
```

El comando muestra el enlace de PayPal directamente en Discord (solo visible para ti). Cualquier cantidad ayuda a cubrir el hosting, la base de datos y los assets.

> **PayPal:** https://paypal.me/Javicez ❤️

Sin donaciones no hay patos, sin patos no hay duelos, sin duelos los peluches se aburren. Ya sabes.

---

## 🛠️ Comandos — Utilidades generales

| Comando | Descripción |
|---|---|
| `/mm` | Explica cómo jugar al minijuego 'mm' |
| `/house howto` | Explica cómo jugar a la Haunted House |
| `/invite` | Genera el enlace de invitación del bot |
| `/donate` | Muestra el enlace de PayPal para apoyar el bot (solo visible para ti) |
| `/translate <texto> <idioma>` | Traduce texto a otro idioma usando Google Translate |
| `/resync_commands` | **(Admin)** Fuerza la re-sincronización de comandos en el servidor |
| `/custom <nombre> <info>` | **(Admin)** Crea un comando personalizado con prefijo `!` para el servidor |
| `/deletecustom <nombre>` | **(Admin)** Elimina un comando personalizado |

### Comandos personalizados

Con `/custom` puedes crear comandos propios que los usuarios invocan con `!nombre`. Por ejemplo:

```
/custom reglas "Aquí están las reglas del servidor: ..."
```

Los usuarios ejecutan `!reglas` y el bot responde con el texto configurado.

---

## 🎲 Monopoly GO — Links automáticos

El bot puede publicar automáticamente los links de recompensas gratuitas de Monopoly GO en un canal designado.

| Comando | Permisos | Descripción |
|---|---|---|
| `/setmonopolychannel <canal> [rol]` | Manage Server | Activa la publicación automática en el canal. `rol` opcional para mencionar |
| `/unsetmonopolychannel` | Manage Server | Desactiva la publicación automática |
| `/monopolyrecentlinks` | Cualquiera | Muestra los links publicados en las últimas 48 horas |

> El bot consulta fuentes externas cada hora y publica únicamente links nuevos que aún no haya publicado.

---

## 🌐 Comandos — Links oficiales

Sistema para guardar y publicar links oficiales del servidor (ej: dados gratis, escudos).

| Comando | Descripción |
|---|---|
| `/set_official_links_channel <canal>` | Configura el canal donde se publicarán los links oficiales |
| `/add_official_link <nombre> <url>` | Añade un link oficial |
| `/remove_official_link <nombre>` | Elimina un link oficial por su nombre |
| `/list_official_links` | Lista todos los links oficiales guardados |
| `/post_official_links` | Publica los links en el canal configurado (o en el canal actual si no hay ninguno) |

---

## 🌍 Comandos — Hora mundial

| Comando | Descripción |
|---|---|
| `/time [zona] [usuario]` | Muestra la hora actual en cualquier zona horaria. Si indicas un usuario, compara tu hora con la suya |
| `/setmytime <zona>` | Guarda tu zona horaria personal (ej: `Europe/Madrid`) |
| `/settimeformat <24h\|12h>` | Elige el formato de hora para ti |

---

## 🔧 Herramientas de desarrollo

### Simulador Teddy Wars (sin Discord)

```bash
python3 -m oceanic_bot.games.teddy_war_sim -n 6
```

### Generar / actualizar assets de pato

```bash
python assets/generate_duck_assets.py
```

### Ejecutar tests

```bash
python tools/run_tests.py
```

### Limpiar comandos de Ocean

```bash
python scripts/clear_ocean_commands.py
```

---

## 🚂 Despliegue en Railway

1. Conecta tu repositorio en [Railway](https://railway.app)
2. Añade las variables de entorno en el panel de Railway (mismas que `.env`)
3. Railway detecta el `Procfile` y ejecuta `python bot.py` automáticamente
4. Los comandos slash se sincronizan automáticamente en cada redeploy

**Variables mínimas necesarias en Railway:**
```
DISCORD_TOKEN=...
DATABASE_URL=...  # Railway proporciona una URL interna de PostgreSQL
```

---

## 📁 Estructura del proyecto

```
bot.py                  → Núcleo del bot y todos los comandos
oceanic_bot/
  games/
    duck.py             → Lógica del minijuego de patos
    ocean_drop.py       → Sistema de drops coleccionables
    custom_wheels.py    → Ruletas personalizables por servidor
    team_teddy_war.py   → Textos e imágenes del Team Teddy War
    teddy_war_sim.py    → Simulador de Teddy Wars sin Discord
  utils/
    time_utils.py       → Utilidades de zonas horarias
assets/                 → Imágenes base de los patos
teddy_wars/             → Assets de imágenes para Teddy Wars
docs/                   → Guías adicionales
requirements.txt        → Dependencias Python
Procfile                → Configuración de despliegue (Railway / Heroku)
```

---

## 📦 Dependencias principales

| Librería | Uso |
|---|---|
| `discord.py >= 2.3` | Framework del bot |
| `asyncpg` | Conexión asíncrona a PostgreSQL |
| `Pillow` | Generación de imágenes (patos, ruletas) |
| `aiohttp` | Peticiones HTTP asíncronas (Monopoly GO) |
| `beautifulsoup4` | Parsing de páginas web (Monopoly GO) |
| `python-dotenv` | Carga de variables de entorno desde `.env` |
| `deep-translator` | Traducción de texto (`/translate`) |

---

## 🐙 Lore — La Flota Friki del Abismo

Cuenta la leyenda que en las profundidades del servidor más caótico, un pato con casco y espada de plástico miró al horizonte digital y dijo: *"Alguien tiene que organizar esto."*

Así nació **Oceanic**.

Los peluches llevan siglos en guerra (nadie recuerda ya por qué, probablemente por el último dado gratis de Monopoly GO). Los patos actúan como árbitros neutrales, aunque siempre acaban duelando entre ellos. Las conchas 🐚 son la moneda más valorada del océano, aunque los Snuggles 🦃 tienen mejor tipo de cambio en la tienda. La Casa Embrujada lleva abandonada desde los 90 y nadie ha encontrado la llave… todavía.

> *"Un bot con brújula propia puede dirigir una flota entera."*
> — Capitán Pato 🦆, fundador de la Flota Friki del Abismo

Si encuentras un bug, probablemente es un cangrejo que se coló en el código. Abre un issue y lo pescamos.

---

> **¿Preguntas o problemas?** Abre un issue en el repositorio o contacta al desarrollador.
