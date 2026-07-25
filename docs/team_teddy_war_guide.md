# Team Teddy War - Guía del Juego / Game Guide

## 🧸 Descripción / Description

### Español
Team Teddy War es un juego de batalla royale por equipos donde ositos de peluche luchan en parejas hasta que solo queda un equipo victorioso. A diferencia del Teddy War tradicional, en este juego los participantes se organizan en equipos de 2 jugadores, y ambos miembros del equipo ganador reciben las recompensas.

### English  
Team Teddy War is a team-based battle royale game where teddy bears fight in pairs until only one victorious team remains. Unlike traditional Teddy War, in this game participants organize into teams of 2 players, and both members of the winning team receive rewards.

---

## 🎮 Cómo Jugar / How to Play

### Español

1. **Crear un Torneo**
   - Usa el comando `/teamteddy` para crear un nuevo torneo
   - Puedes personalizar el título del torneo
   - El creador del torneo es el anfitrión (host)

2. **Unirse a un Equipo**
   - Usa el comando `/jointeamteddy` para abrir el menú de selección de equipos
   - Verás botones para los equipos disponibles (1-10)
   - Los equipos llenos (2 jugadores) NO aparecerán como opción
   - Solo puedes estar en UN equipo
   - Cada equipo necesita exactamente 2 jugadores para participar

3. **Iniciar la Batalla**
   - El anfitrión (o un administrador) puede iniciar cuando esté listo
   - Se necesitan mínimo 2 equipos completos (4 jugadores totales)
   - No es necesario llenar todos los 10 equipos

4. **La Batalla**
   - Los equipos luchan automáticamente en batallas emocionantes
   - Se muestran imágenes de los ositos durante las peleas
   - Mensajes divertidos narran la acción
   - Solo un equipo sobrevivirá

5. **Victoria**
   - El equipo ganador se muestra con la imagen `victory.png`
   - AMBOS jugadores del equipo ganador reciben:
     - Moneda del servidor (3x número total de participantes)
     - Victoria registrada en estadísticas
   - La batalla termina

### English

1. **Create a Tournament**
   - Use the `/teamteddy` command to create a new tournament
   - You can customize the tournament title
   - The tournament creator is the host

2. **Join a Team**
   - Use the `/jointeamteddy` command to open the team selection menu
   - You'll see buttons for available teams (1-10)
   - Full teams (2 players) will NOT appear as options
   - You can only be on ONE team
   - Each team needs exactly 2 players to participate

3. **Start the Battle**
   - The host (or an administrator) can start when ready
   - Minimum 2 complete teams required (4 total players)
   - It's not necessary to fill all 10 teams

4. **The Battle**
   - Teams fight automatically in exciting battles
   - Teddy images are shown during fights
   - Funny messages narrate the action
   - Only one team will survive

5. **Victory**
   - The winning team is shown with the `victory.png` image
   - BOTH players on the winning team receive:
     - Server currency (3x total number of participants)
     - Victory recorded in stats
   - The battle ends

---

## 🎯 Características / Features

### Español
- ✅ Equipos de 2 jugadores
- ✅ Máximo 10 equipos (20 jugadores)
- ✅ Botones dinámicos (solo muestra equipos disponibles)
- ✅ Imágenes únicas de teddy_wars2/
- ✅ Imagen especial de victoria (victory.png)
- ✅ Mensajes divertidos y graciosos
- ✅ Soporte multiidioma (español/inglés)
- ✅ Recompensas para ambos ganadores
- ✅ Ataques sincronizados y trabajos en equipo

### English
- ✅ Teams of 2 players
- ✅ Maximum 10 teams (20 players)
- ✅ Dynamic buttons (only shows available teams)
- ✅ Unique images from teddy_wars2/
- ✅ Special victory image (victory.png)
- ✅ Funny and entertaining messages
- ✅ Multi-language support (Spanish/English)
- ✅ Rewards for both winners
- ✅ Synchronized attacks and teamwork

---

## 📁 Archivos / Files

### Assets
- **Directorio:** `teddy_wars2/`
- **Imágenes de batalla:** IMG_*.png (15 imágenes)
- **Imagen de victoria:** victory.png

### Código / Code
- **Módulo principal:** `oceanic_bot/games/team_teddy_war.py`
- **Integración:** `bot.py` (clases y comandos)

---

## 🎨 Mensajes de Batalla / Battle Messages

El juego incluye diferentes tipos de mensajes:

### Ataques / Attacks
Describen cómo los equipos atacan juntos con combos especiales y movimientos sincronizados.

### Eliminaciones / Eliminations  
Celebran dramáticamente cuando un equipo es eliminado del juego.

### Victoria / Victory
Coronan al equipo ganador con mensajes épicos.

### Burlas / Taunts
Mensajes opcionales donde los equipos se burlan de sus oponentes.

---

## 🔧 Comandos / Commands

| Comando | Descripción (ES) | Description (EN) |
|---------|------------------|------------------|
| `/teamteddy [título]` | Crear un torneo de Team Teddy War | Create a Team Teddy War tournament |
| `/jointeamteddy` | Abrir menú para unirse a un equipo | Open menu to join a team |

---

## 💡 Consejos / Tips

### Español
- **Estrategia de equipo:** Coordina con tu compañero antes de la batalla (aunque es automática, ¡es más divertido!)
- **Timing:** El anfitrión puede iniciar en cualquier momento, no esperes a llenar todos los equipos
- **Equipos impares:** Si un equipo tiene solo 1 jugador, NO participará en la batalla
- **Recompensas:** Cuantos más participantes, mayor la recompensa para los ganadores

### English
- **Team strategy:** Coordinate with your partner before battle (though it's automatic, it's more fun!)
- **Timing:** The host can start anytime, don't wait to fill all teams
- **Incomplete teams:** If a team has only 1 player, it will NOT participate in battle
- **Rewards:** More participants = bigger rewards for winners

---

## 🆚 Diferencias con Teddy War Original / Differences from Original Teddy War

| Característica | Teddy War | Team Teddy War |
|----------------|-----------|----------------|
| Jugadores por partida | Individual | Equipos de 2 |
| Comando | `/teddy_war` | `/teamteddy` |
| Unirse | Botón directo | `/jointeamteddy` menú |
| Ganadores | 1 jugador | 2 jugadores (equipo) |
| Imágenes | teddy_wars/ | teddy_wars2/ |
| Victoria | winner*.png | victory.png |
| Máximo participantes | 50 | 20 (10 equipos) |

---

## 🌍 Multilenguaje / Multi-language

El juego detecta automáticamente el idioma configurado del servidor:
- **Español:** Todos los textos en español
- **English:** All texts in English

El idioma se determina usando `get_guild_language()` que lee la configuración del servidor.

---

¡Disfruta de la batalla de ositos! / Enjoy the teddy bear battle! 🧸⚔️🧸
