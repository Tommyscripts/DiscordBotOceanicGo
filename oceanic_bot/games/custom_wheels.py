"""
Custom Wheels System - Per-server customizable wheels/roulettes
"""
from __future__ import annotations
import asyncio
import random
import math
import time
from typing import Optional, List, TYPE_CHECKING
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    import asyncpg

# Modal for configuring custom wheel options
class CustomWheelOptionsModal(discord.ui.Modal, title="Configure Wheel Options"):
    """Modal that dynamically generates text inputs for each option name."""
    
    def __init__(self, num_options: int, existing_options: Optional[List[str]] = None):
        super().__init__(timeout=600)  # 10 minute timeout
        self.num_options = num_options
        self.option_values = {}
        
        # Discord modals can only have up to 5 text inputs at a time
        # So we'll split into multiple modals if needed
        max_inputs = min(5, num_options)
        
        for i in range(max_inputs):
            default_value = existing_options[i] if existing_options and i < len(existing_options) else ""
            text_input = discord.ui.TextInput(
                label=f"Option {i + 1}",
                placeholder=f"Enter name for option {i + 1}",
                default=default_value,
                required=True,
                max_length=100,
                style=discord.TextStyle.short
            )
            self.add_item(text_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Collect the values from the modal."""
        for i, item in enumerate(self.children):
            if isinstance(item, discord.ui.TextInput):
                self.option_values[i] = item.value.strip()
        
        await interaction.response.defer()


class CustomWheelSetupView(discord.ui.View):
    """View with buttons to configure the custom wheel step by step."""
    
    def __init__(self, guild_id: int, db_pool, user_id: int):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.db_pool = db_pool
        self.user_id = user_id
        self.num_options = 2
        self.all_options: List[str] = []
        self.current_batch = 0
        
    @discord.ui.button(label="Set Number of Options (2+)", style=discord.ButtonStyle.primary, custom_id="set_num")
    async def set_number(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set the number of options for the wheel."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the user who started setup can configure this.", ephemeral=True)
            return
        
        # Create a modal to ask for number
        class NumberModal(discord.ui.Modal, title="Number of Options"):
            num_input = discord.ui.TextInput(
                label="How many options? (minimum 2)",
                placeholder="Enter a number between 2 and 50",
                required=True,
                max_length=3,
                style=discord.TextStyle.short
            )
            
            async def on_submit(self, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer()
        
        modal = NumberModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        
        try:
            num = int(modal.num_input.value)
            if num < 2:
                await interaction.followup.send("Number must be at least 2.", ephemeral=True)
                return
            if num > 50:
                await interaction.followup.send("Maximum 50 options for performance reasons.", ephemeral=True)
                return
            
            self.num_options = num
            self.all_options = [""] * num
            self.current_batch = 0
            
            await interaction.followup.send(
                f"✅ Set to {num} options. Now click 'Configure Options' to name them.",
                ephemeral=True
            )
        except ValueError:
            await interaction.followup.send("Please enter a valid number.", ephemeral=True)
    
    @discord.ui.button(label="Configure Options", style=discord.ButtonStyle.secondary, custom_id="config_opts")
    async def configure_options(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Configure option names in batches of 5."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the user who started setup can configure this.", ephemeral=True)
            return
        
        # Calculate which batch we're on
        options_per_batch = 5
        start_idx = self.current_batch * options_per_batch
        end_idx = min(start_idx + options_per_batch, self.num_options)
        
        if start_idx >= self.num_options:
            await interaction.response.send_message("All options have been configured!", ephemeral=True)
            return
        
        # Get existing values for this batch
        batch_options = self.all_options[start_idx:end_idx]
        
        # Create modal for this batch
        modal = CustomWheelOptionsModal(
            num_options=end_idx - start_idx,
            existing_options=batch_options
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        
        # Store the values
        for local_idx, value in modal.option_values.items():
            global_idx = start_idx + local_idx
            if global_idx < self.num_options:
                self.all_options[global_idx] = value
        
        self.current_batch += 1
        
        # Check if we need more batches
        if end_idx < self.num_options:
            remaining = self.num_options - end_idx
            await interaction.followup.send(
                f"✅ Options {start_idx + 1}-{end_idx} configured. {remaining} more to go. Click 'Configure Options' again.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"✅ All {self.num_options} options configured! Click 'Save' to finalize.",
                ephemeral=True
            )
    
    @discord.ui.button(label="💾 Save Wheel", style=discord.ButtonStyle.success, custom_id="save")
    async def save_wheel(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save the configured wheel to the database."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the user who started setup can save this.", ephemeral=True)
            return
        
        # Validate all options are filled
        if any(not opt or opt == "" for opt in self.all_options):
            await interaction.response.send_message(
                "Please configure all options before saving. Some options are empty.",
                ephemeral=True
            )
            return
        
        # Save to database
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO custom_wheels (guild_id, options, created_at, updated_at)
                    VALUES ($1, $2, $3, $3)
                    ON CONFLICT (guild_id)
                    DO UPDATE SET options = $2, updated_at = $3
                    """,
                    self.guild_id,
                    self.all_options,
                    int(time.time())
                )
            
            options_preview = ", ".join(self.all_options[:5])
            if len(self.all_options) > 5:
                options_preview += "..."
            
            await interaction.response.send_message(
                f"✅ **Custom wheel saved!**\n"
                f"Options ({len(self.all_options)}): {options_preview}\n\n"
                f"Use `/customwheels spin` to spin your custom wheel!",
                ephemeral=False
            )
            
            # Disable all buttons
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            
            await interaction.message.edit(view=self)
            self.stop()
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error saving wheel: {e}",
                ephemeral=True
            )
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the setup."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the user who started setup can cancel this.", ephemeral=True)
            return
        
        await interaction.response.send_message("Setup cancelled.", ephemeral=True)
        
        # Disable all buttons
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        await interaction.message.edit(view=self)
        self.stop()


async def _init_custom_wheels_tables(db_pool) -> None:
    """Create the custom_wheels table if it doesn't exist."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_wheels (
                guild_id BIGINT PRIMARY KEY,
                options TEXT[] NOT NULL,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL
            )
            """
        )


def _generate_wheel_image(options: List[str], winner_idx: int) -> Optional[BytesIO]:
    """
    Generate an animated GIF of a spinning wheel that lands on winner_idx.
    Returns a BytesIO buffer with the GIF data, or None if generation fails.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import colorsys
    except ImportError:
        return None
    
    try:
        size = 800
        center = size // 2
        num = len(options)
        
        # Generate distinct colors per option using HSV spacing
        colors = []
        for i in range(num):
            h = float(i) / max(1, num)
            s = 0.85
            v = 0.95
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            colors.append((int(r*255), int(g*255), int(b*255)))
        
        # Create base wheel image
        base = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        bdraw = ImageDraw.Draw(base)
        bbox = (20, 20, size-20, size-20)
        bdraw.ellipse(bbox, fill=(240, 240, 240), outline=(0, 0, 0), width=3)
        
        # Draw wedges
        for i in range(num):
            start_angle = 360.0 * i / num
            end_angle = 360.0 * (i+1) / num
            color = colors[i % len(colors)]
            bdraw.pieslice(bbox, start=-start_angle, end=-end_angle, fill=color, outline=(255, 255, 255), width=2)
        
        # Draw center circle
        center_radius = 80
        bdraw.ellipse(
            (center-center_radius, center-center_radius, center+center_radius, center+center_radius),
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            width=2
        )
        
        # Render option labels
        labels = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        ldraw = ImageDraw.Draw(labels)
        
        # Adaptive font sizing
        try:
            base_font_size = max(12, min(24, int(220 / max(4, num))))
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", base_font_size)
        except Exception:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
        
        for i, option_name in enumerate(options):
            start_angle = 360.0 * i / num
            end_angle = 360.0 * (i+1) / num
            mid_angle = (start_angle + end_angle) / 2
            r = int((size/2 - 60) * 0.75)
            theta = mid_angle * (math.pi/180.0)
            tx = int(center + r * -math.sin(theta))
            ty = int(center + r * -math.cos(theta))
            
            text = option_name
            # Truncate if too long
            max_len = 18
            if len(text) > max_len:
                text = text[:max_len-1] + "…"
            
            # Get text size
            try:
                bbox_text = ldraw.textbbox((0, 0), text, font=font)
                tw = bbox_text[2] - bbox_text[0]
                th = bbox_text[3] - bbox_text[1]
            except Exception:
                tw, th = (80, 20)
            
            # Draw background rectangle
            pad_x = 8
            pad_y = 5
            rect = (
                int(tx - tw//2 - pad_x),
                int(ty - th//2 - pad_y),
                int(tx + tw//2 + pad_x),
                int(ty + th//2 + pad_y)
            )
            ldraw.rectangle(rect, fill=(255, 255, 255, 230))
            
            # Draw text
            if font:
                ldraw.text((tx - tw//2, ty - th//2), text, font=font, fill=(0, 0, 0))
            else:
                ldraw.text((tx - tw//2, ty - th//2), text, fill=(0, 0, 0))
        
        # Combine base + labels
        wheel_img = Image.alpha_composite(base, labels)
        
        # Generate animated frames
        target_mid = (360.0 * winner_idx / num + 360.0 * (winner_idx+1) / num) / 2
        target_rotation = -target_mid
        
        start_rotation = random.uniform(0, 360)
        total_turns = random.uniform(3, 5)
        final_rotation = start_rotation + total_turns * 360 + target_rotation
        
        frames = []
        frame_count = 40
        
        for f in range(frame_count):
            t = f / (frame_count - 1)
            ease = 1 - pow(1 - t, 3)
            rot = start_rotation + (final_rotation - start_rotation) * ease
            
            # Rotate wheel
            rotated = wheel_img.rotate(rot, resample=Image.BICUBIC, center=(center, center))
            
            # Add pointer at top
            pointer_img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
            pdraw = ImageDraw.Draw(pointer_img)
            pointer_points = [
                (center, 40),
                (center - 20, 80),
                (center + 20, 80)
            ]
            pdraw.polygon(pointer_points, fill=(255, 0, 0), outline=(0, 0, 0))
            
            frame = Image.alpha_composite(rotated, pointer_img)
            frames.append(frame.convert("RGB"))
        
        # Save as GIF
        buf = BytesIO()
        frames[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=80,
            loop=0
        )
        buf.seek(0)
        
        return buf
        
    except Exception as e:
        print(f"Error generating wheel image: {e}")
        return None


class CustomWheelsCog(commands.Cog):
    """Cog for custom wheels functionality."""
    
    def __init__(self, bot: commands.Bot, db_pool):
        self.bot = bot
        self.db_pool = db_pool
    
    async def cog_load(self):
        """Initialize database tables when cog loads."""
        await _init_custom_wheels_tables(self.db_pool)
    
    @app_commands.command(name="customwheels-settings", description="Configure your server's custom wheel")
    @app_commands.guild_only()
    async def customwheels_settings(self, interaction: discord.Interaction):
        """Settings command to configure the custom wheel."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        # Check if user has manage_guild permission
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You need 'Manage Server' permission to configure the custom wheel.",
                ephemeral=True
            )
            return
        
        guild_id = interaction.guild.id
        
        # Check if wheel already exists
        existing = None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT options FROM custom_wheels WHERE guild_id = $1",
                    guild_id
                )
                if row:
                    existing = row['options']
        except Exception:
            pass
        
        if existing:
            existing_preview = ", ".join(existing[:5])
            if len(existing) > 5:
                existing_preview += "..."
            
            confirm_msg = (
                f"⚠️ This server already has a custom wheel with {len(existing)} options:\n"
                f"{existing_preview}\n\n"
                f"Do you want to reconfigure it? This will replace the existing wheel."
            )
        else:
            confirm_msg = "Let's set up your server's custom wheel! Follow the steps below:"
        
        # Create the setup view
        view = CustomWheelSetupView(guild_id, self.db_pool, interaction.user.id)
        
        embed = discord.Embed(
            title="🎡 Custom Wheel Setup",
            description=confirm_msg,
            color=0x00FF00
        )
        embed.add_field(
            name="Steps",
            value=(
                "1️⃣ Click **'Set Number of Options'** to choose how many options (minimum 2)\n"
                "2️⃣ Click **'Configure Options'** to name each option (you may need to do this multiple times)\n"
                "3️⃣ Click **'Save Wheel'** to finalize and save\n"
                "4️⃣ Use `/customwheels-spin` to spin your wheel!"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
    
    @app_commands.command(name="customwheels-spin", description="Spin your server's custom wheel")
    @app_commands.guild_only()
    async def customwheels_spin(self, interaction: discord.Interaction):
        """Spin the custom wheel and pick a random option."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = interaction.guild.id
        
        # Fetch the wheel configuration
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT options FROM custom_wheels WHERE guild_id = $1",
                    guild_id
                )
                
                if not row:
                    await interaction.response.send_message(
                        "❌ This server doesn't have a custom wheel configured yet!\n"
                        "Use `/customwheels-settings` to create one.",
                        ephemeral=True
                    )
                    return
                
                options = row['options']
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error fetching wheel configuration: {e}",
                ephemeral=True
            )
            return
        
        if not options or len(options) < 2:
            await interaction.response.send_message(
                "❌ The custom wheel has invalid configuration. Please reconfigure it with `/customwheels-settings`.",
                ephemeral=True
            )
            return
        
        # Pick random winner
        winner_idx = random.randint(0, len(options) - 1)
        winner = options[winner_idx]
        
        # Acknowledge the spin
        await interaction.response.send_message(
            f"🎡 Spinning the custom wheel with {len(options)} options...",
            ephemeral=False
        )
        
        # Generate wheel image
        img_buffer = _generate_wheel_image(options, winner_idx)
        
        # Send result
        embed = discord.Embed(
            title="🎉 Custom Wheel Result",
            description=f"**The wheel landed on:** {winner}",
            color=0xFFD700
        )
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        if img_buffer:
            file = discord.File(img_buffer, filename="custom_wheel.gif")
            embed.set_image(url="attachment://custom_wheel.gif")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="customwheels-view", description="View your server's custom wheel configuration")
    @app_commands.guild_only()
    async def customwheels_view(self, interaction: discord.Interaction):
        """View the current custom wheel configuration."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = interaction.guild.id
        
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT options, created_at, updated_at FROM custom_wheels WHERE guild_id = $1",
                    guild_id
                )
                
                if not row:
                    await interaction.response.send_message(
                        "❌ This server doesn't have a custom wheel configured yet!\n"
                        "Use `/customwheels-settings` to create one.",
                        ephemeral=True
                    )
                    return
                
                options = row['options']
                created_at = row['created_at']
                updated_at = row['updated_at']
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error fetching wheel configuration: {e}",
                ephemeral=True
            )
            return
        
        # Format options list
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
        
        # Truncate if too long
        if len(options_text) > 1000:
            visible_options = []
            char_count = 0
            for i, opt in enumerate(options):
                line = f"{i+1}. {opt}\n"
                if char_count + len(line) > 950:
                    visible_options.append(f"... and {len(options) - i} more options")
                    break
                visible_options.append(f"{i+1}. {opt}")
                char_count += len(line)
            options_text = "\n".join(visible_options)
        
        embed = discord.Embed(
            title="🎡 Custom Wheel Configuration",
            description=f"**Total Options:** {len(options)}",
            color=0x3498DB
        )
        embed.add_field(name="Options", value=options_text, inline=False)
        embed.set_footer(text=f"Last updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(updated_at))}")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup_custom_wheels(bot: commands.Bot, db_pool) -> None:
    """Setup function to add the CustomWheels cog to the bot."""
    await bot.add_cog(CustomWheelsCog(bot, db_pool))
