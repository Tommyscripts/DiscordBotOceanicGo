"""
ocean_drop_game.py — 🌊 Ocean Drop Collectible Game

Comandos:
  /ocean_drop      – Lanza un drop manual (random o canal específico)
  /ocean_active    – Activa drops automáticos aleatorios en la temporada
  /ocean_seasonends – Termina la temporada y muestra el top 10
  /give_collectible  – (Staff) Dar un coleccionable a un miembro
  /remove_collectible – (Staff) Quitar un coleccionable a un miembro
  /view_collection – Ver la colección de otro miembro
  /collection      – Ver tu propia colección
  /trade           – Proponer un intercambio con otro miembro
  /leaderboard     – Top 10 de coleccionistas de la temporada

Integración en bot.py → ver la función setup_ocean_drop() al final del archivo.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ─── Coleccionables de la temporada ──────────────────────────────────────────

SUMMER_COLLECTIBLES: dict[str, str] = {
    "Ocean Shell":    "🐚",
    "Hibiscus Charm": "🌺",
    "Golden Coconut": "🥥",
    "Sunset Crystal": "🔮",
    "Surf Token":     "🏄",
    "Wave Fragment":  "🌊",
}

COLLECTIBLE_NAMES = list(SUMMER_COLLECTIBLES.keys())


# ─── DB helpers (tablas propias del módulo) ───────────────────────────────────

async def _init_ocean_tables(pool) -> None:
    """Crea las tablas necesarias si no existen."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ocean_season_config (
                guild_id         BIGINT  PRIMARY KEY,
                active           BOOLEAN NOT NULL DEFAULT FALSE,
                drop_role_id     BIGINT,
                complete_role_id BIGINT,
                season_name      TEXT    NOT NULL DEFAULT 'Summer Splash',
                min_minutes      INTEGER NOT NULL DEFAULT 30,
                max_minutes      INTEGER NOT NULL DEFAULT 120
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ocean_inventory (
                guild_id  BIGINT NOT NULL,
                user_id   BIGINT NOT NULL,
                item_name TEXT   NOT NULL,
                quantity  INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (guild_id, user_id, item_name)
            )
            """
        )


# ─── Vista: botón de reclamación del Drop ────────────────────────────────────

class OceanDropView(discord.ui.View):
    def __init__(self, item_name: str, item_emoji: str, cog: "OceanDropCog"):
        super().__init__(timeout=None)
        self.item_name  = item_name
        self.item_emoji = item_emoji
        self.cog        = cog
        self.claimed    = False

    @discord.ui.button(label="¡Reclamar!", emoji="🐚", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            await interaction.response.send_message("¡Ya fue reclamado!", ephemeral=True)
            return

        self.claimed      = True
        button.disabled   = True
        button.label      = f"Reclamado por {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)

        # Agregar item al inventario
        await self.cog._add_item(interaction.guild_id, interaction.user.id, self.item_name)

        embed = discord.Embed(
            title       = f"{self.item_emoji} ¡Reclamado!",
            description = (
                f"**{interaction.user.display_name}** ganó "
                f"**{self.item_name}** {self.item_emoji}!"
            ),
            color = 0x00BFFF,
        )
        await interaction.followup.send(embed=embed)

        # Verificar si completó la colección
        if await self.cog._check_complete(
            interaction.guild_id, interaction.user.id, interaction.guild
        ):
            await self.cog._announce_complete(interaction, interaction.user)

        self.stop()


# ─── Vista: botón de aceptar/rechazar Trade ──────────────────────────────────

class TradeView(discord.ui.View):
    def __init__(
        self,
        proposer : discord.Member,
        target   : discord.Member,
        offer    : str,
        request  : str,
        cog      : "OceanDropCog",
    ):
        super().__init__(timeout=120)
        self.proposer = proposer
        self.target   = target
        self.offer    = offer
        self.request  = request
        self.cog      = cog
        self.done     = False

    @discord.ui.button(label="✅ Aceptar", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "Este trade no es para ti.", ephemeral=True
            )
            return
        if self.done:
            await interaction.response.send_message(
                "Este trade ya fue procesado.", ephemeral=True
            )
            return

        self.done = True

        # Verificar que ambas partes sigan teniendo sus items
        if not await self.cog._has_item(interaction.guild_id, self.proposer.id, self.offer):
            await interaction.response.edit_message(
                content=f"❌ {self.proposer.display_name} ya no tiene **{self.offer}**.",
                embed=None, view=None,
            )
            self.stop()
            return

        if not await self.cog._has_item(interaction.guild_id, self.target.id, self.request):
            await interaction.response.edit_message(
                content=f"❌ Ya no tienes **{self.request}**.",
                embed=None, view=None,
            )
            self.stop()
            return

        # Ejecutar el intercambio
        await self.cog._remove_item(interaction.guild_id, self.proposer.id, self.offer)
        await self.cog._remove_item(interaction.guild_id, self.target.id, self.request)
        await self.cog._add_item(interaction.guild_id, self.target.id, self.offer)
        await self.cog._add_item(interaction.guild_id, self.proposer.id, self.request)

        offer_emoji   = SUMMER_COLLECTIBLES.get(self.offer, "")
        request_emoji = SUMMER_COLLECTIBLES.get(self.request, "")
        embed = discord.Embed(
            title       = "🤝 ¡Trade completado!",
            description = (
                f"{self.proposer.mention} entregó **{self.offer}** {offer_emoji}\n"
                f"{self.target.mention} entregó **{self.request}** {request_emoji}"
            ),
            color = 0x00CC66,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="❌ Rechazar", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.target.id, self.proposer.id):
            await interaction.response.send_message(
                "No puedes cancelar este trade.", ephemeral=True
            )
            return
        if self.done:
            return
        self.done = True
        await interaction.response.edit_message(
            content="❌ Trade rechazado.", embed=None, view=None
        )
        self.stop()


# ─── Cog principal ────────────────────────────────────────────────────────────

class OceanDropCog(commands.Cog, name="OceanDropCog"):
    """Juego de coleccionables: Ocean Drop."""

    def __init__(self, bot: commands.Bot, db_pool):
        self.bot     = bot
        self.db_pool = db_pool
        self._auto_drop_tasks: dict[int, asyncio.Task] = {}

    # ── Helpers de BD ─────────────────────────────────────────────────────────

    async def _get_config(self, guild_id: int) -> dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ocean_season_config WHERE guild_id = $1", guild_id
            )
        return dict(row) if row else {}

    async def _set_config(self, guild_id: int, **kwargs) -> None:
        keys   = list(kwargs.keys())
        values = list(kwargs.values())
        set_clause = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(keys))
        placeholders = ", ".join(f"${i + 2}" for i in range(len(keys)))
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO ocean_season_config (guild_id, {', '.join(keys)})
                VALUES ($1, {placeholders})
                ON CONFLICT (guild_id) DO UPDATE SET {set_clause}
                """,
                guild_id, *values,
            )

    async def _add_item(self, guild_id: int, user_id: int, item_name: str) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ocean_inventory (guild_id, user_id, item_name, quantity)
                VALUES ($1, $2, $3, 1)
                ON CONFLICT (guild_id, user_id, item_name)
                DO UPDATE SET quantity = ocean_inventory.quantity + 1
                """,
                guild_id, user_id, item_name,
            )

    async def _remove_item(self, guild_id: int, user_id: int, item_name: str) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ocean_inventory
                SET quantity = quantity - 1
                WHERE guild_id = $1 AND user_id = $2 AND item_name = $3
                """,
                guild_id, user_id, item_name,
            )
            await conn.execute(
                """
                DELETE FROM ocean_inventory
                WHERE guild_id = $1 AND user_id = $2 AND item_name = $3
                  AND quantity <= 0
                """,
                guild_id, user_id, item_name,
            )

    async def _has_item(self, guild_id: int, user_id: int, item_name: str) -> bool:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT quantity FROM ocean_inventory
                WHERE guild_id = $1 AND user_id = $2 AND item_name = $3
                """,
                guild_id, user_id, item_name,
            )
        return row is not None and row["quantity"] > 0

    async def _get_inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT item_name, quantity FROM ocean_inventory
                WHERE guild_id = $1 AND user_id = $2
                """,
                guild_id, user_id,
            )
        return {r["item_name"]: r["quantity"] for r in rows}

    async def _check_complete(
        self, guild_id: int, user_id: int, guild: discord.Guild
    ) -> bool:
        inv = await self._get_inventory(guild_id, user_id)
        return all(inv.get(name, 0) > 0 for name in SUMMER_COLLECTIBLES)

    async def _get_leaderboard(self, guild_id: int) -> list[dict]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id,
                       COUNT(DISTINCT item_name) AS unique_items,
                       SUM(quantity)             AS total
                FROM ocean_inventory
                WHERE guild_id = $1
                GROUP BY user_id
                ORDER BY unique_items DESC, total DESC
                LIMIT 10
                """,
                guild_id,
            )
        return [dict(r) for r in rows]

    # ── Helpers internos ──────────────────────────────────────────────────────

    async def _announce_complete(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """Publica el embed de colección completa y asigna el rol del drop al miembro."""
        cfg          = await self._get_config(interaction.guild_id)
        season_name  = cfg.get("season_name", "Summer Splash")
        drop_role_id = cfg.get("drop_role_id")
        drop_role    = (
            interaction.guild.get_role(drop_role_id) if drop_role_id else None
        )
        embed = discord.Embed(
            title       = "🏖️ ¡COLECCIÓN COMPLETA!",
            description = (
                f"¡Felicidades {member.mention}! Coleccionaste todos los "
                f"{len(SUMMER_COLLECTIBLES)} items de **{season_name}** y desbloqueaste:\n\n"
                + (f"🌊 Rol **{drop_role.name}**\n" if drop_role else "")
                + "🎁 ¡Bonus reward!"
            ),
            color = 0xFFD700,
        )
        await interaction.followup.send(embed=embed)
        if drop_role:
            try:
                await member.add_roles(drop_role, reason="Ocean Drop – colección completa")
            except Exception:
                log.exception("[OceanDrop] No se pudo asignar el rol de colección completa")

    async def _announce_complete_channel(
        self,
        channel  : discord.TextChannel,
        guild    : discord.Guild,
        user_id  : int,
    ) -> None:
        """Versión de _announce_complete para usarse sin Interaction (ej: desde Teddy Wars)."""
        cfg          = await self._get_config(guild.id)
        season_name  = cfg.get("season_name", "Summer Splash")
        drop_role_id = cfg.get("drop_role_id")
        drop_role    = guild.get_role(drop_role_id) if drop_role_id else None
        member       = guild.get_member(user_id)
        mention      = f"<@{user_id}>"
        embed = discord.Embed(
            title       = "🏖️ ¡COLECCIÓN COMPLETA!",
            description = (
                f"¡Felicidades {mention}! Coleccionaste todos los "
                f"{len(SUMMER_COLLECTIBLES)} items de **{season_name}** y desbloqueaste:\n\n"
                + (f"🌊 Rol **{drop_role.name}**\n" if drop_role else "")
                + "🎁 ¡Bonus reward!"
            ),
            color = 0xFFD700,
        )
        await channel.send(embed=embed)
        if drop_role and member:
            try:
                await member.add_roles(drop_role, reason="Ocean Drop – colección completa")
            except Exception:
                log.exception("[OceanDrop] No se pudo asignar el rol de colección completa")

    async def _get_drop_channels(
        self, guild: discord.Guild, role_id: int
    ) -> list[discord.TextChannel]:
        """Devuelve los canales de texto donde el rol dado puede ver mensajes."""
        role = guild.get_role(role_id)
        if role is None:
            return []
        return [ch for ch in guild.text_channels if ch.permissions_for(role).view_channel]

    async def _do_drop(
        self,
        channel  : discord.TextChannel,
        item_name: Optional[str] = None,
    ) -> None:
        """Envía el embed de drop con botón de reclamación."""
        if item_name is None:
            item_name = random.choice(COLLECTIBLE_NAMES)
        emoji       = SUMMER_COLLECTIBLES.get(item_name, "🐚")
        cfg         = await self._get_config(channel.guild.id)
        season_name = cfg.get("season_name", "Summer Splash")

        embed = discord.Embed(
            title       = f"🌊 {season_name.upper()} DROP!",
            description = (
                f"¡Sé el primero en hacer clic en {emoji} y gana el coleccionable "
                f"**{item_name}**!"
            ),
            color = 0x00BFFF,
        )
        view = OceanDropView(item_name, emoji, self)
        await channel.send(embed=embed, view=view)

    async def _auto_drop_loop(self, guild_id: int) -> None:
        """Bucle en segundo plano que lanza drops automáticos aleatorios."""
        while True:
            cfg = await self._get_config(guild_id)
            if not cfg.get("active", False):
                break

            min_m = cfg.get("min_minutes", 30)
            max_m = cfg.get("max_minutes", 120)
            await asyncio.sleep(random.randint(min_m * 60, max_m * 60))

            # Re-verificar después de esperar
            cfg = await self._get_config(guild_id)
            if not cfg.get("active", False):
                break

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                break

            role_id = cfg.get("drop_role_id")
            if not role_id:
                continue

            channels = await self._get_drop_channels(guild, role_id)
            if not channels:
                continue

            try:
                await self._do_drop(random.choice(channels))
            except Exception:
                log.exception("[OceanDrop] Error en auto-drop para guild %s", guild_id)

    # ── Comandos ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "ocean_drop",
        description = "🌊 Lanza un drop de coleccionable (elige random o canal específico)",
    )
    @app_commands.describe(
        modo  = "'random' para canal aleatorio según el rol configurado, 'canal' para elegir uno",
        canal = "Canal destino del drop (solo cuando modo = canal)",
        item  = "Item a dropear. Si no se elige, será aleatorio",
    )
    @app_commands.choices(
        modo=[
            app_commands.Choice(name="🎲 Random (canal aleatorio)", value="random"),
            app_commands.Choice(name="📢 Canal específico",         value="canal"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ocean_drop(
        self,
        interaction : discord.Interaction,
        modo        : app_commands.Choice[str],
        canal       : Optional[discord.TextChannel] = None,
        item        : Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if item and item not in SUMMER_COLLECTIBLES:
            await interaction.followup.send(
                f"❌ Item inválido. Opciones: {', '.join(COLLECTIBLE_NAMES)}",
                ephemeral=True,
            )
            return

        if modo.value == "random":
            cfg     = await self._get_config(interaction.guild_id)
            role_id = cfg.get("drop_role_id")
            if role_id:
                channels = await self._get_drop_channels(interaction.guild, role_id)
                target: discord.TextChannel = (
                    random.choice(channels) if channels else interaction.channel
                )
            else:
                # Sin rol configurado → cualquier canal donde el bot pueda escribir
                visible = [
                    ch for ch in interaction.guild.text_channels
                    if ch.permissions_for(interaction.guild.me).send_messages
                ]
                target = random.choice(visible) if visible else interaction.channel
        else:
            target = canal or interaction.channel

        await interaction.followup.send(
            f"✅ Lanzando drop en {target.mention}!", ephemeral=True
        )
        await self._do_drop(target, item)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "ocean_active",
        description = "🌊 Activa los drops automáticos aleatorios de la temporada",
    )
    @app_commands.describe(
        rol              = "Rol que define los canales de drop y se otorga al completar la colección",
        nombre_temporada = "Nombre de la temporada (por defecto: Summer Splash)",
        min_minutos      = "Mínimo de minutos entre drops (por defecto: 30)",
        max_minutos      = "Máximo de minutos entre drops (por defecto: 120)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ocean_active(
        self,
        interaction      : discord.Interaction,
        rol              : discord.Role,
        nombre_temporada : Optional[str] = "Summer Splash",
        min_minutos      : Optional[int] = 30,
        max_minutos      : Optional[int] = 120,
    ):
        await interaction.response.defer(ephemeral=True)

        if min_minutos < 1:
            await interaction.followup.send(
                "❌ `min_minutos` debe ser al menos 1.", ephemeral=True
            )
            return
        if max_minutos < min_minutos:
            await interaction.followup.send(
                "❌ `max_minutos` debe ser mayor o igual que `min_minutos`.", ephemeral=True
            )
            return

        # Cancelar tarea anterior si existía
        if interaction.guild_id in self._auto_drop_tasks:
            self._auto_drop_tasks[interaction.guild_id].cancel()

        # El mismo rol sirve para determinar canales Y como recompensa de colección completa
        await self._set_config(
            interaction.guild_id,
            active       = True,
            drop_role_id = rol.id,
            season_name  = nombre_temporada or "Summer Splash",
            min_minutes  = min_minutos,
            max_minutes  = max_minutos,
        )

        task = asyncio.create_task(self._auto_drop_loop(interaction.guild_id))
        self._auto_drop_tasks[interaction.guild_id] = task

        channels = await self._get_drop_channels(interaction.guild, rol.id)
        embed = discord.Embed(
            title       = "🌊 ¡Temporada activada!",
            description = (
                f"**{nombre_temporada}** ha comenzado.\n\n"
                f"🎯 Canales elegibles: **{len(channels)}** "
                f"(canales visibles para {rol.mention})\n"
                f"⏱️ Drops cada: **{min_minutos}–{max_minutos}** minutos\n"
                f"🏆 Al completar la colección se otorgará: {rol.mention}"
            ),
            color = 0x00BFFF,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "ocean_seasonends",
        description = "🌊 Termina la temporada, detiene los drops y muestra el top 10",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ocean_seasonends(self, interaction: discord.Interaction):
        await interaction.response.defer()

        cfg         = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")

        if interaction.guild_id in self._auto_drop_tasks:
            self._auto_drop_tasks[interaction.guild_id].cancel()
            del self._auto_drop_tasks[interaction.guild_id]

        await self._set_config(interaction.guild_id, active=False)

        rows   = await self._get_leaderboard(interaction.guild_id)
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines: list[str] = []

        for i, row in enumerate(rows):
            try:
                member = (
                    interaction.guild.get_member(row["user_id"])
                    or await interaction.guild.fetch_member(row["user_id"])
                )
                name = member.display_name
            except Exception:
                name = f"Usuario {row['user_id']}"
            lines.append(
                f"{medals[i]} **{name}** — "
                f"{row['unique_items']} únicos / {row['total']} total"
            )

        embed = discord.Embed(
            title       = f"🌊 FIN DE TEMPORADA — {season_name}",
            description = (
                "\n".join(lines) if lines else "Nadie coleccionó nada esta temporada."
            ),
            color = 0xFF6B35,
        )
        embed.set_footer(text="¡Gracias por participar! Hasta la próxima temporada 🌊")
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "give_collectible",
        description = "(Staff) Dar un coleccionable a un miembro",
    )
    @app_commands.describe(
        miembro = "Miembro que recibirá el item",
        item    = "Nombre del coleccionable",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def give_collectible(
        self,
        interaction : discord.Interaction,
        miembro     : discord.Member,
        item        : str,
    ):
        if item not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(
                f"❌ Item inválido. Opciones: {', '.join(COLLECTIBLE_NAMES)}",
                ephemeral=True,
            )
            return

        await self._add_item(interaction.guild_id, miembro.id, item)
        emoji = SUMMER_COLLECTIBLES[item]
        await interaction.response.send_message(
            f"✅ {emoji} **{item}** entregado a {miembro.mention}.", ephemeral=True
        )

        if await self._check_complete(interaction.guild_id, miembro.id, interaction.guild):
            await self._announce_complete(interaction, miembro)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "remove_collectible",
        description = "(Staff) Quitar un coleccionable a un miembro",
    )
    @app_commands.describe(
        miembro = "Miembro al que se le quitará el item",
        item    = "Nombre del coleccionable",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_collectible(
        self,
        interaction : discord.Interaction,
        miembro     : discord.Member,
        item        : str,
    ):
        if item not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(
                f"❌ Item inválido. Opciones: {', '.join(COLLECTIBLE_NAMES)}",
                ephemeral=True,
            )
            return
        if not await self._has_item(interaction.guild_id, miembro.id, item):
            await interaction.response.send_message(
                f"❌ {miembro.display_name} no tiene **{item}**.", ephemeral=True
            )
            return

        await self._remove_item(interaction.guild_id, miembro.id, item)
        emoji = SUMMER_COLLECTIBLES[item]
        await interaction.response.send_message(
            f"✅ {emoji} **{item}** eliminado de la colección de {miembro.mention}.",
            ephemeral=True,
        )

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "view_collection",
        description = "Ver la colección de coleccionables de un miembro",
    )
    @app_commands.describe(miembro="Miembro cuya colección quieres ver")
    async def view_collection(
        self, interaction: discord.Interaction, miembro: discord.Member
    ):
        await interaction.response.defer()
        inv         = await self._get_inventory(interaction.guild_id, miembro.id)
        cfg         = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        collected   = sum(1 for n in SUMMER_COLLECTIBLES if inv.get(n, 0) > 0)

        lines = []
        for name, emoji in SUMMER_COLLECTIBLES.items():
            qty     = inv.get(name, 0)
            qty_str = f" ×{qty}" if qty > 1 else ""
            estado  = "✅" if qty > 0 else "❌"
            lines.append(f"{emoji} **{name}**{qty_str}: {estado}")

        embed = discord.Embed(
            title       = f"🌊 Colección de {miembro.display_name}",
            description = "\n".join(lines),
            color       = 0x00BFFF,
        )
        embed.set_footer(
            text=(
                f"🏖️ ¡Colección {season_name} COMPLETA!"
                if collected == len(SUMMER_COLLECTIBLES)
                else f"{collected}/{len(SUMMER_COLLECTIBLES)} coleccionables obtenidos"
            )
        )
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "collection",
        description = "🌊 Ver tu propia colección de coleccionables",
    )
    async def collection(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        inv         = await self._get_inventory(interaction.guild_id, interaction.user.id)
        cfg         = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        collected   = sum(1 for n in SUMMER_COLLECTIBLES if inv.get(n, 0) > 0)

        lines = []
        for name, emoji in SUMMER_COLLECTIBLES.items():
            qty     = inv.get(name, 0)
            qty_str = f" ×{qty}" if qty > 1 else ""
            estado  = "✅" if qty > 0 else "❌"
            lines.append(f"{emoji} **{name}**{qty_str}: {estado}")

        embed = discord.Embed(
            title       = f"🌊 Tu Colección — {season_name}",
            description = "\n".join(lines),
            color       = 0x00BFFF,
        )
        embed.set_footer(
            text=(
                "🏖️ ¡Colección COMPLETA! Eres un Summer Collector 🌊"
                if collected == len(SUMMER_COLLECTIBLES)
                else f"{collected}/{len(SUMMER_COLLECTIBLES)} coleccionables obtenidos"
            )
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "trade",
        description = "🤝 Proponer un intercambio de coleccionables con otro miembro",
    )
    @app_commands.describe(
        miembro = "Miembro con quien tradear",
        oferta  = "Coleccionable que ofreces",
        peticion= "Coleccionable que pides a cambio",
    )
    async def trade(
        self,
        interaction : discord.Interaction,
        miembro     : discord.Member,
        oferta      : str,
        peticion    : str,
    ):
        if oferta not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(
                f"❌ Oferta inválida. Opciones: {', '.join(COLLECTIBLE_NAMES)}",
                ephemeral=True,
            )
            return
        if peticion not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(
                f"❌ Petición inválida. Opciones: {', '.join(COLLECTIBLE_NAMES)}",
                ephemeral=True,
            )
            return
        if miembro.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ No puedes tradear contigo mismo.", ephemeral=True
            )
            return
        if not await self._has_item(interaction.guild_id, interaction.user.id, oferta):
            await interaction.response.send_message(
                f"❌ No tienes **{oferta}** para ofrecer.", ephemeral=True
            )
            return
        if not await self._has_item(interaction.guild_id, miembro.id, peticion):
            await interaction.response.send_message(
                f"❌ {miembro.display_name} no tiene **{peticion}**.", ephemeral=True
            )
            return

        offer_emoji   = SUMMER_COLLECTIBLES[oferta]
        request_emoji = SUMMER_COLLECTIBLES[peticion]
        embed = discord.Embed(
            title       = "🤝 Propuesta de Trade",
            description = (
                f"{interaction.user.mention} ofrece **{oferta}** {offer_emoji}\n"
                f"A cambio de **{peticion}** {request_emoji} de {miembro.mention}\n\n"
                f"{miembro.mention}, ¿aceptas el trade?"
            ),
            color = 0xFFA500,
        )
        view = TradeView(interaction.user, miembro, oferta, peticion, self)
        await interaction.response.send_message(embed=embed, view=view)

    # ──────────────────────────────────────────────────────────────────────────

    @app_commands.command(
        name        = "leaderboard",
        description = "🌊 Ver el top 10 de coleccionistas de la temporada",
    )
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows        = await self._get_leaderboard(interaction.guild_id)
        cfg         = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        medals      = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines: list[str] = []

        for i, row in enumerate(rows):
            try:
                member = (
                    interaction.guild.get_member(row["user_id"])
                    or await interaction.guild.fetch_member(row["user_id"])
                )
                name = member.display_name
            except Exception:
                name = f"Usuario {row['user_id']}"
            lines.append(
                f"{medals[i]} **{name}** — "
                f"{row['unique_items']} únicos / {row['total']} total"
            )

        embed = discord.Embed(
            title       = f"🌊 Leaderboard — {season_name}",
            description = (
                "\n".join(lines) if lines else "Nadie ha coleccionado nada todavía."
            ),
            color = 0x00BFFF,
        )
        await interaction.followup.send(embed=embed)


# ─── Función de setup (llamada desde bot.py) ─────────────────────────────────

async def setup_ocean_drop(bot: commands.Bot, db_pool) -> OceanDropCog:
    """
    Inicializa las tablas de BD y registra el Cog en el bot.

    Uso en bot.py (dentro de on_connect, después de init_db_async()):

        from ocean_drop_game import setup_ocean_drop, _init_ocean_tables

        # En on_connect:
        if not bot.cogs.get("OceanDropCog"):
            await _init_ocean_tables(db_pool)
            cog = await setup_ocean_drop(bot, db_pool)
    """
    await _init_ocean_tables(db_pool)
    cog = OceanDropCog(bot, db_pool)
    await bot.add_cog(cog)
    return cog
