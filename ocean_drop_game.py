"""
ocean_drop_game.py — 🌊 Ocean Drop Collectible Game

Comandos:
  /ocean_drop      – Lanza un drop manual (random o canal específico)
"""

from __future__ import annotations
from typing import Optional
import random
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# Example collectible map (should exist elsewhere in your real code)
SUMMER_COLLECTIBLES = {
    "conch": "🐚",
    "starfish": "⭐",
    "shell": "🐚",
}
COLLECTIBLE_NAMES = list(SUMMER_COLLECTIBLES.keys())


# ─── Translations (simple i18n) ─────────────────────────────────────────────
TRANSLATIONS: dict[str, dict[str, str]] = {
    "claim_button": {"es": "¡Reclamar!", "en": "Claim!"},
    "claim_already": {"es": "¡Ya fue reclamado!", "en": "Already claimed!"},
    "claimed_by": {"es": "Reclamado por {name}", "en": "Claimed by {name}"},

    "claimed_title": {"es": "{emoji} ¡Reclamado!", "en": "{emoji} Claimed!"},
    "won_item": {"es": "**{name}** ganó **{item}** {emoji}!", "en": "**{name}** won **{item}** {emoji}!"},
    "drop_title": {"es": "🌊 {season} DROP!", "en": "🌊 {season} DROP!"},
    "drop_description": {
        "es": "¡Sé el primero en hacer clic en {emoji} y gana el coleccionable **{item}**!",
        "en": "Be the first to click {emoji} and win the collectible **{item}**!",
    },

    "trade_accept": {"es": "✅ Aceptar", "en": "✅ Accept"},
    "trade_reject": {"es": "❌ Rechazar", "en": "❌ Reject"},
    "trade_not_for_you": {"es": "Este trade no es para ti.", "en": "This trade is not for you."},
    "trade_already_processed": {"es": "Este trade ya fue procesado.", "en": "This trade has already been processed."},
    "proposer_no_longer_has": {"es": "❌ {proposer} ya no tiene **{offer}**.", "en": "❌ {proposer} no longer has **{offer}**."},
    "target_no_longer_has": {"es": "❌ Ya no tienes **{request}**.", "en": "❌ You no longer have **{request}**."},
    "trade_completed_title": {"es": "🤝 ¡Trade completado!", "en": "🤝 Trade completed!"},
    "trade_completed_desc": {
        "es": "{a} entregó **{offer}** {offer_emoji}\\n{b} entregó **{request}** {request_emoji}",
        "en": "{a} gave **{offer}** {offer_emoji}\\n{b} gave **{request}** {request_emoji}",
    },
    "trade_proposal_title": {"es": "🤝 Propuesta de Trade", "en": "🤝 Trade Proposal"},
    "trade_proposal_desc": {
        "es": "{proposer} ofrece **{offer}** {offer_emoji}\\nA cambio de **{request}** {request_emoji} de {target}\\n\\n{target}, ¿aceptas el trade?",
        "en": "{proposer} offers **{offer}** {offer_emoji}\\nIn exchange for **{request}** {request_emoji} from {target}\\n\\n{target}, do you accept the trade?",
    },
    "trade_cannot_self": {"es": "❌ No puedes tradear contigo mismo.", "en": "❌ You cannot trade with yourself."},
    "cannot_cancel_trade": {"es": "No puedes cancelar este trade.", "en": "You cannot cancel this trade."},
    "trade_rejected": {"es": "❌ Trade rechazado.", "en": "❌ Trade rejected."},

    "collection_complete_title": {"es": "🏖️ ¡COLECCIÓN COMPLETA!", "en": "🏖️ COLLECTION COMPLETE!"},
    "collection_complete_role": {"es": "🌊 Rol **{role}**\\n", "en": "🌊 Role **{role}**\\n"},
    "collection_complete_desc": {
        "es": "¡Felicidades {mention}! Coleccionaste todos los {count} items de **{season}** y desbloqueaste:\\n\\n{role_line}🎁 ¡Recompensa extra!",
        "en": "Congratulations {mention}! You collected all the {count} items of **{season}** and unlocked:\\n\\n{role_line}🎁 Bonus reward!",
    },

    "season_activated_title": {"es": "🌊 ¡Temporada activada!", "en": "🌊 Season activated!"},
    "season_activated_desc": {
        "es": "**{season}** ha comenzado.\\n\\n🎯 Canales elegibles: **{channels}** (canales visibles para {role})\\n⏱️ Drops cada: **{min}–{max}** minutos\\n🏆 Al completar la colección se otorgará: {role}",
        "en": "**{season}** has started.\\n\\n🎯 Eligible channels: **{channels}** (visible for {role})\\n⏱️ Drops every: **{min}–{max}** minutes\\n🏆 On completion the role granted will be: {role}",
    },

    "launching_drop": {"es": "✅ Lanzando drop en {target}!", "en": "✅ Launching drop in {target}!"},

    "invalid_item": {"es": "❌ Item inválido. Opciones: {options}", "en": "❌ Invalid item. Options: {options}"},
    "given_item": {"es": "✅ {emoji} **{item}** entregado a {member}.", "en": "✅ {emoji} **{item}** given to {member}."},
    "removed_item": {"es": "✅ {emoji} **{item}** eliminado de la colección de {member}.", "en": "✅ {emoji} **{item}** removed from {member}'s collection."},
    "does_not_have_item": {"es": "❌ {member} no tiene **{item}**.", "en": "❌ {member} does not have **{item}**."},

    "collection_title": {"es": "🌊 Colección de {name}", "en": "🌊 Collection of {name}"},
    "collection_footer_complete": {"es": "🏖️ ¡Colección {season} COMPLETA!", "en": "🏖️ Collection {season} COMPLETE!"},
    "collection_footer_progress": {"es": "{collected}/{total} coleccionables obtenidos", "en": "{collected}/{total} collectibles obtained"},

    "season_end_title": {"es": "🌊 FIN DE TEMPORADA — {season}", "en": "🌊 SEASON END — {season}"},
    "season_end_empty": {"es": "Nadie coleccionó nada esta temporada.", "en": "No one collected anything this season."},
    "season_end_footer": {"es": "¡Gracias por participar! Hasta la próxima temporada 🌊", "en": "Thanks for participating! See you next season 🌊"},
    "leaderboard_empty": {"es": "Nadie ha coleccionado nada todavía.", "en": "No one has collected anything yet."},
    "leaderboard_user_fallback": {"es": "Usuario {id}", "en": "User {id}"},
    "leaderboard_entry": {"es": "{medal} **{name}** — {unique} únicos / {total} total", "en": "{medal} **{name}** — {unique} unique / {total} total"},

    "min_minutes_error": {"es": "❌ `min_minutos` debe ser al menos 1.", "en": "❌ `min_minutes` must be at least 1."},
    "max_minutes_error": {"es": "❌ `max_minutos` debe ser mayor o igual que `min_minutos`.", "en": "❌ `max_minutes` must be greater or equal to `min_minutes`."},
}


# ─── i18n helpers ───────────────────────────────────────────────────────────
def _lang_for_guild(guild: Optional[discord.Guild]) -> str:
    """Return 'es' or 'en' based on guild.preferred_locale. Defaults to 'en'."""
    if not guild:
        return "en"
    loc = getattr(guild, "preferred_locale", "") or ""
    return "es" if str(loc).lower().startswith("es") else "en"


def _t(guild: Optional[discord.Guild], key: str, **kwargs) -> str:
    """Translate a key for a guild (simple lookup with fallback)."""
    lang = _lang_for_guild(guild)
    mapping = TRANSLATIONS.get(key, {})
    text = mapping.get(lang) or mapping.get("en") or mapping.get("es") or key
    try:
        return text.format(**kwargs)
    except Exception:
        return text


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
    def __init__(
        self,
        item_name: str,
        item_emoji: str,
        cog: "OceanDropCog",
        guild: Optional[discord.Guild] = None,
    ):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.item_emoji = item_emoji
        self.cog = cog
        self.claimed = False
        self.guild = guild

        # Create localized claim button
        label = _t(self.guild, "claim_button")
        btn = discord.ui.Button(label=label, emoji=self.item_emoji, style=discord.ButtonStyle.primary)

        async def _on_claim(interaction: discord.Interaction):
            if self.claimed:
                await interaction.response.send_message(_t(self.guild, "claim_already"), ephemeral=True)
                return

            self.claimed = True
            btn.disabled = True
            btn.label = _t(self.guild, "claimed_by", name=interaction.user.display_name)
            await interaction.response.edit_message(view=self)

            # Add item to inventory
            await self.cog._add_item(interaction.guild_id, interaction.user.id, self.item_name)

            embed = discord.Embed(
                title=_t(self.guild, "claimed_title", emoji=self.item_emoji),
                description=_t(
                    self.guild,
                    "won_item",
                    name=interaction.user.display_name,
                    item=self.item_name,
                    emoji=self.item_emoji,
                ),
                color=0x00BFFF,
            )
            await interaction.followup.send(embed=embed)

            # Check completion
            if await self.cog._check_complete(
                interaction.guild_id, interaction.user.id, interaction.guild
            ):
                await self.cog._announce_complete(interaction, interaction.user)

            self.stop()

        btn.callback = _on_claim
        self.add_item(btn)


# ─── Vista: botón de aceptar/rechazar Trade ──────────────────────────────────
class TradeView(discord.ui.View):
    def __init__(
        self,
        proposer : discord.Member,
        target   : discord.Member,
        offer    : str,
        request  : str,
        cog      : "OceanDropCog",
        guild    : Optional[discord.Guild] = None,
    ):
        super().__init__(timeout=120)
        self.proposer = proposer
        self.target = target
        self.offer = offer
        self.request = request
        self.cog = cog
        self.done = False
        self.guild = guild

        accept_label = _t(self.guild, "trade_accept")
        reject_label = _t(self.guild, "trade_reject")

        btn_accept = discord.ui.Button(label=accept_label, style=discord.ButtonStyle.success)
        btn_reject = discord.ui.Button(label=reject_label, style=discord.ButtonStyle.danger)

        async def _accept(interaction: discord.Interaction):
            if interaction.user.id != self.target.id:
                await interaction.response.send_message(_t(self.guild, "trade_not_for_you"), ephemeral=True)
                return
            if self.done:
                await interaction.response.send_message(_t(self.guild, "trade_already_processed"), ephemeral=True)
                return

            self.done = True

            if not await self.cog._has_item(interaction.guild_id, self.proposer.id, self.offer):
                await interaction.response.edit_message(
                    content=_t(self.guild, "proposer_no_longer_has", proposer=self.proposer.display_name, offer=self.offer),
                    embed=None, view=None,
                )
                self.stop()
                return

            if not await self.cog._has_item(interaction.guild_id, self.target.id, self.request):
                await interaction.response.edit_message(
                    content=_t(self.guild, "target_no_longer_has", request=self.request),
                    embed=None, view=None,
                )
                self.stop()
                return

            await self.cog._remove_item(interaction.guild_id, self.proposer.id, self.offer)
            await self.cog._remove_item(interaction.guild_id, self.target.id, self.request)
            await self.cog._add_item(interaction.guild_id, self.target.id, self.offer)
            await self.cog._add_item(interaction.guild_id, self.proposer.id, self.request)

            offer_emoji = SUMMER_COLLECTIBLES.get(self.offer, "")
            request_emoji = SUMMER_COLLECTIBLES.get(self.request, "")
            embed = discord.Embed(
                title=_t(self.guild, "trade_completed_title"),
                description=_t(
                    self.guild,
                    "trade_completed_desc",
                    a=self.proposer.mention,
                    offer=self.offer,
                    offer_emoji=offer_emoji,
                    b=self.target.mention,
                    request=self.request,
                    request_emoji=request_emoji,
                ),
                color=0x00CC66,
            )
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()

        async def _reject(interaction: discord.Interaction):
            if interaction.user.id not in (self.target.id, self.proposer.id):
                await interaction.response.send_message(_t(self.guild, "cannot_cancel_trade"), ephemeral=True)
                return
            if self.done:
                return
            self.done = True
            await interaction.response.edit_message(content=_t(self.guild, "trade_rejected"), embed=None, view=None)
            self.stop()

        btn_accept.callback = _accept
        btn_reject.callback = _reject
        self.add_item(btn_accept)
        self.add_item(btn_reject)


# ─── Cog principal ────────────────────────────────────────────────────────────
class OceanDropCog(commands.Cog, name="OceanDropCog"):
    """Juego de coleccionables: Ocean Drop."""

    def __init__(self, bot: commands.Bot, db_pool):
        self.bot = bot
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
        keys = list(kwargs.keys())
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
        cfg = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        drop_role_id = cfg.get("drop_role_id")
        drop_role = (
            interaction.guild.get_role(drop_role_id) if drop_role_id else None
        )
        role_line = _t(interaction.guild, "collection_complete_role", role=drop_role.name) if drop_role else ""
        desc = _t(
            interaction.guild,
            "collection_complete_desc",
            mention=member.mention,
            count=len(SUMMER_COLLECTIBLES),
            season=season_name,
            role_line=role_line,
        )
        embed = discord.Embed(title=_t(interaction.guild, "collection_complete_title"), description=desc, color=0xFFD700)
        await interaction.followup.send(embed=embed)
        if drop_role:
            try:
                await member.add_roles(drop_role, reason="Ocean Drop – colección completa")
            except Exception:
                log.exception("[OceanDrop] No se pudo asignar el rol de colección completa")

    async def _announce_complete_channel(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        user_id: int,
    ) -> None:
        """Versión de _announce_complete para usarse sin Interaction (ej: desde Teddy Wars)."""
        cfg = await self._get_config(guild.id)
        season_name = cfg.get("season_name", "Summer Splash")
        drop_role_id = cfg.get("drop_role_id")
        drop_role = guild.get_role(drop_role_id) if drop_role_id else None
        member = guild.get_member(user_id)
        mention = f"<@{user_id}>"
        role_line = _t(guild, "collection_complete_role", role=drop_role.name) if drop_role else ""
        desc = _t(
            guild,
            "collection_complete_desc",
            mention=mention,
            count=len(SUMMER_COLLECTIBLES),
            season=season_name,
            role_line=role_line,
        )
        embed = discord.Embed(title=_t(guild, "collection_complete_title"), description=desc, color=0xFFD700)
        await channel.send(embed=embed)
        if drop_role and member:
            try:
                await member.add_roles(drop_role, reason="Ocean Drop – colección completa")
            except Exception:
                log.exception("[OceanDrop] No se pudo asignar el rol de colección completa")

    async def _get_drop_channels(
        self, guild: discord.Guild, role_id: int
    ) -> list[discord.TextChannel]:
        role = guild.get_role(role_id)
        if role is None:
            return []
        return [ch for ch in guild.text_channels if ch.permissions_for(role).view_channel]

    async def _do_drop(
        self,
        channel: discord.TextChannel,
        item_name: Optional[str] = None,
    ) -> None:
        """Envía el embed de drop con botón de reclamación."""
        if item_name is None:
            item_name = random.choice(COLLECTIBLE_NAMES)
        emoji = SUMMER_COLLECTIBLES.get(item_name, "🐚")
        cfg = await self._get_config(channel.guild.id)
        season_name = cfg.get("season_name", "Summer Splash")

        embed = discord.Embed(
            title=_t(channel.guild, "drop_title", season=season_name.upper()),
            description=_t(channel.guild, "drop_description", emoji=emoji, item=item_name),
            color=0x00BFFF,
        )
        view = OceanDropView(item_name, emoji, self, channel.guild)
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

        # ------------------ Commands (registered as app commands) ------------------
    @app_commands.command(
        name="ocean_drop",
        description="🌊 Launch a manual drop (random or specific channel)",
        description_localizations={"es-ES": "🌊 Lanza un drop manual (random o canal específico)", "es-MX": "🌊 Lanza un drop manual (random o canal específico)"},
    )
    @app_commands.choices(modo=[app_commands.Choice(name="random", value="random"), app_commands.Choice(name="channel", value="channel")])
    @app_commands.describe(
        modo="Modo: random|channel",
        canal="Canal de destino (opcional)",
        item="Item específico (opcional)",
    )
    async def ocean_drop(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        canal: Optional[discord.TextChannel] = None,
        item: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if item and item not in SUMMER_COLLECTIBLES:
            await interaction.followup.send(
                _t(interaction.guild, "invalid_item", options=", ".join(COLLECTIBLE_NAMES)),
                ephemeral=True,
            )
            return

        if modo.value == "random":
            cfg = await self._get_config(interaction.guild_id)
            role_id = cfg.get("drop_role_id")
            if role_id:
                channels = await self._get_drop_channels(interaction.guild, role_id)
                target: discord.TextChannel = (
                    random.choice(channels) if channels else interaction.channel
                )
            else:
                visible = [
                    ch for ch in interaction.guild.text_channels
                    if ch.permissions_for(interaction.guild.me).send_messages
                ]
                target = random.choice(visible) if visible else interaction.channel
        else:
            target = canal or interaction.channel

        await interaction.followup.send(
            _t(interaction.guild, "launching_drop", target=target.mention), ephemeral=True
        )
        await self._do_drop(target, item)

    @app_commands.command(
        name="ocean_active",
        description="🌊 Activa los drops automáticos aleatorios de la temporada",
        description_localizations={"en-US": "🌊 Enable automatic season drops (random).", "en-GB": "🌊 Enable automatic season drops (random)."},
    )
    @app_commands.describe(
        rol="Rol que define los canales de drop y se otorga al completar la colección",
        nombre_temporada="Nombre de la temporada (por defecto: Summer Splash)",
        min_minutos="Mínimo de minutos entre drops (por defecto: 30)",
        max_minutos="Máximo de minutos entre drops (por defecto: 120)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ocean_active(self, interaction: discord.Interaction, rol: discord.Role, nombre_temporada: Optional[str] = "Summer Splash", min_minutos: Optional[int] = 30, max_minutos: Optional[int] = 120):
        await interaction.response.defer(ephemeral=True)
        if min_minutos < 1:
            await interaction.followup.send(_t(interaction.guild, "min_minutes_error"), ephemeral=True)
            return
        if max_minutos < min_minutos:
            await interaction.followup.send(_t(interaction.guild, "max_minutes_error"), ephemeral=True)
            return

        if interaction.guild_id in self._auto_drop_tasks:
            self._auto_drop_tasks[interaction.guild_id].cancel()

        await self._set_config(
            interaction.guild_id,
            active=True,
            drop_role_id=rol.id,
            season_name=nombre_temporada or "Summer Splash",
            min_minutes=min_minutos,
            max_minutes=max_minutos,
        )

        task = asyncio.create_task(self._auto_drop_loop(interaction.guild_id))
        self._auto_drop_tasks[interaction.guild_id] = task

        channels = await self._get_drop_channels(interaction.guild, rol.id)
        desc = _t(
            interaction.guild,
            "season_activated_desc",
            season=nombre_temporada or "Summer Splash",
            channels=len(channels),
            role=rol.mention,
            min=min_minutos,
            max=max_minutos,
        )
        embed = discord.Embed(title=_t(interaction.guild, "season_activated_title"), description=desc, color=0x00BFFF)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ocean_seasonends",
        description="🌊 Termina la temporada, detiene los drops y muestra el top 10",
        description_localizations={"en-US": "🌊 End the season, stop drops and show top 10.", "en-GB": "🌊 End the season, stop drops and show top 10."},
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ocean_seasonends(self, interaction: discord.Interaction):
        await interaction.response.defer()

        cfg = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")

        if interaction.guild_id in self._auto_drop_tasks:
            self._auto_drop_tasks[interaction.guild_id].cancel()
            del self._auto_drop_tasks[interaction.guild_id]

        await self._set_config(interaction.guild_id, active=False)

        rows = await self._get_leaderboard(interaction.guild_id)
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines: list[str] = []

        for i, row in enumerate(rows):
            try:
                member = (
                    interaction.guild.get_member(row["user_id"]) or await interaction.guild.fetch_member(row["user_id"]) 
                )
                name = member.display_name
            except Exception:
                name = _t(interaction.guild, "leaderboard_user_fallback", id=row["user_id"])
            lines.append(_t(interaction.guild, "leaderboard_entry", medal=medals[i], name=name, unique=row["unique_items"], total=row["total"]))

        title = _t(interaction.guild, "season_end_title", season=season_name)
        description = "\n".join(lines) if lines else _t(interaction.guild, "season_end_empty")
        embed = discord.Embed(title=title, description=description, color=0xFF6B35)
        embed.set_footer(text=_t(interaction.guild, "season_end_footer"))
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="give_collectible",
        description="(Staff) Dar un coleccionable a un miembro",
        description_localizations={"en-US": "(Staff) Give a collectible to a member."},
    )
    @app_commands.describe(miembro="Miembro que recibirá el item", item="Nombre del coleccionable")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def give_collectible(self, interaction: discord.Interaction, miembro: discord.Member, item: str):
        if item not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(_t(interaction.guild, "invalid_item", options=", ".join(COLLECTIBLE_NAMES)), ephemeral=True)
            return
        await self._add_item(interaction.guild_id, miembro.id, item)
        emoji = SUMMER_COLLECTIBLES[item]
        await interaction.response.send_message(_t(interaction.guild, "given_item", emoji=emoji, item=item, member=miembro.mention), ephemeral=True)
        if await self._check_complete(interaction.guild_id, miembro.id, interaction.guild):
            await self._announce_complete(interaction, miembro)

    @app_commands.command(
        name="remove_collectible",
        description="(Staff) Quitar un coleccionable a un miembro",
        description_localizations={"en-US": "(Staff) Remove a collectible from a member."},
    )
    @app_commands.describe(miembro="Miembro al que se le quitará el item", item="Nombre del coleccionable")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_collectible(self, interaction: discord.Interaction, miembro: discord.Member, item: str):
        if item not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(_t(interaction.guild, "invalid_item", options=", ".join(COLLECTIBLE_NAMES)), ephemeral=True)
            return
        if not await self._has_item(interaction.guild_id, miembro.id, item):
            await interaction.response.send_message(_t(interaction.guild, "does_not_have_item", member=miembro.display_name, item=item), ephemeral=True)
            return
        await self._remove_item(interaction.guild_id, miembro.id, item)
        emoji = SUMMER_COLLECTIBLES[item]
        await interaction.response.send_message(_t(interaction.guild, "removed_item", emoji=emoji, item=item, member=miembro.mention), ephemeral=True)

    @app_commands.command(
        name="view_collection",
        description="Ver la colección de coleccionables de un miembro",
        description_localizations={"en-US": "View a member's collectibles collection."},
    )
    @app_commands.describe(miembro="Miembro cuya colección quieres ver")
    async def view_collection(self, interaction: discord.Interaction, miembro: discord.Member):
        await interaction.response.defer()
        inv = await self._get_inventory(interaction.guild_id, miembro.id)
        cfg = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        collected = sum(1 for n in SUMMER_COLLECTIBLES if inv.get(n, 0) > 0)

        lines = []
        for name, emoji in SUMMER_COLLECTIBLES.items():
            qty = inv.get(name, 0)
            qty_str = f" ×{qty}" if qty > 1 else ""
            estado = "✅" if qty > 0 else "❌"
            lines.append(f"{emoji} **{name}**{qty_str}: {estado}")

        embed = discord.Embed(title=_t(interaction.guild, "collection_title", name=miembro.display_name), description="\n".join(lines), color=0x00BFFF)
        footer = _t(interaction.guild, "collection_footer_complete", season=season_name) if collected == len(SUMMER_COLLECTIBLES) else _t(interaction.guild, "collection_footer_progress", collected=collected, total=len(SUMMER_COLLECTIBLES))
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="collection",
        description="🌊 Ver tu propia colección de coleccionables",
        description_localizations={"en-US": "🌊 View your own collectibles collection."},
    )
    async def collection(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        inv = await self._get_inventory(interaction.guild_id, interaction.user.id)
        cfg = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        collected = sum(1 for n in SUMMER_COLLECTIBLES if inv.get(n, 0) > 0)

        lines = []
        for name, emoji in SUMMER_COLLECTIBLES.items():
            qty = inv.get(name, 0)
            qty_str = f" ×{qty}" if qty > 1 else ""
            estado = "✅" if qty > 0 else "❌"
            lines.append(f"{emoji} **{name}**{qty_str}: {estado}")

        embed = discord.Embed(title=_t(interaction.guild, "collection_title", name=interaction.user.display_name) + f" — {season_name}", description="\n".join(lines), color=0x00BFFF)
        footer = _t(interaction.guild, "collection_footer_complete", season=season_name) if collected == len(SUMMER_COLLECTIBLES) else _t(interaction.guild, "collection_footer_progress", collected=collected, total=len(SUMMER_COLLECTIBLES))
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="trade",
        description="🤝 Proponer un intercambio de coleccionables con otro miembro",
        description_localizations={"en-US": "🤝 Propose a collectible trade with another member."},
    )
    @app_commands.describe(miembro="Miembro con quien tradear", oferta="Coleccionable que ofreces", peticion="Coleccionable que pides a cambio")
    async def trade(self, interaction: discord.Interaction, miembro: discord.Member, oferta: str, peticion: str):
        if oferta not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(_t(interaction.guild, "invalid_item", options=", ".join(COLLECTIBLE_NAMES)), ephemeral=True)
            return
        if peticion not in SUMMER_COLLECTIBLES:
            await interaction.response.send_message(_t(interaction.guild, "invalid_item", options=", ".join(COLLECTIBLE_NAMES)), ephemeral=True)
            return
        if miembro.id == interaction.user.id:
            await interaction.response.send_message(_t(interaction.guild, "trade_cannot_self"), ephemeral=True)
            return
        if not await self._has_item(interaction.guild_id, interaction.user.id, oferta):
            await interaction.response.send_message(_t(interaction.guild, "does_not_have_item", member=interaction.user.display_name, item=oferta), ephemeral=True)
            return
        if not await self._has_item(interaction.guild_id, miembro.id, peticion):
            await interaction.response.send_message(_t(interaction.guild, "does_not_have_item", member=miembro.display_name, item=peticion), ephemeral=True)
            return

        offer_emoji = SUMMER_COLLECTIBLES[oferta]
        request_emoji = SUMMER_COLLECTIBLES[peticion]
        embed = discord.Embed(title=_t(interaction.guild, "trade_proposal_title"), description=_t(interaction.guild, "trade_proposal_desc", proposer=interaction.user.mention, offer=oferta, offer_emoji=offer_emoji, request=peticion, request_emoji=request_emoji, target=miembro.mention), color=0xFFA500)
        view = TradeView(interaction.user, miembro, oferta, peticion, self, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="leaderboard",
        description="🌊 Ver el top 10 de coleccionistas de la temporada",
        description_localizations={"en-US": "🌊 View the season's top 10 collectors."},
    )
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self._get_leaderboard(interaction.guild_id)
        cfg = await self._get_config(interaction.guild_id)
        season_name = cfg.get("season_name", "Summer Splash")
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines: list[str] = []

        for i, row in enumerate(rows):
            try:
                member = (
                    interaction.guild.get_member(row["user_id"]) or await interaction.guild.fetch_member(row["user_id"]) 
                )
                name = member.display_name
            except Exception:
                name = _t(interaction.guild, "leaderboard_user_fallback", id=row["user_id"])
            lines.append(_t(interaction.guild, "leaderboard_entry", medal=medals[i], name=name, unique=row["unique_items"], total=row["total"]))

        embed = discord.Embed(title=f"🌊 Leaderboard — {season_name}", description="\n".join(lines) if lines else _t(interaction.guild, "leaderboard_empty"), color=0x00BFFF)
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
