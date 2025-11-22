import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
import aiohttp
import asyncio
import logging
from database import DatabaseManager
from embeds import create_account_embed, create_success_embed, create_error_embed, create_info_embed, create_skin_info_embed, create_skin_embed
from minecraft_api import MinecraftApiService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 0)) if os.getenv('CHANNEL_ID') else None

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)


async def verify_minecraft_skin(ign: str) -> tuple[bool, str, str]:
    """
    Verify if an IGN has a valid Minecraft skin using Mojang API
    Returns: (has_skin, uuid, error_message)
    """
    try:
        logger.info(f"Verifying skin for IGN: {ign}")
        
        # Get player info from Mojang API with retry logic
        player_info = await MinecraftApiService.get_player_info(ign)
        
        logger.info(f"Player info response: {player_info}")
        
        if not player_info:
            logger.warning(f"Player not found for IGN: {ign}")
            return False, "", "Player not found on Mojang API"
        
        uuid = player_info.get('id')
        if not uuid:
            logger.warning(f"No UUID found for IGN: {ign}")
            return False, "", "Could not retrieve UUID"
        
        logger.info(f"UUID found: {uuid}")
        
        # Try multiple skin endpoints to verify
        skin_verified = False
        skin_endpoints = [
            f"https://skins.mcstats.com/head/{uuid}",
            f"https://mc-heads.net/head/{uuid}",
            f"https://crafatar.com/avatars/{uuid}"
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                for skin_url in skin_endpoints:
                    try:
                        async with session.head(skin_url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as resp:
                            logger.info(f"Skin check {skin_url}: {resp.status}")
                            if resp.status == 200:
                                skin_verified = True
                                logger.info(f"✅ Skin verified at {skin_url}")
                                break
                    except Exception as e:
                        logger.debug(f"Error checking {skin_url}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error during skin verification: {e}")
            # If we got a UUID, consider it a valid account even if we can't verify skin
            return True, uuid, f"Account verified (skin check failed: {str(e)})"
        
        if skin_verified:
            return True, uuid, "Skin verified"
        else:
            # Fallback: if we got a UUID from Mojang, consider it valid
            logger.warning(f"Could not verify skin via endpoints for {uuid}, but account exists on Mojang")
            return True, uuid, "Account verified (skin check unavailable)"
    
    except Exception as e:
        logger.error(f"Error verifying skin: {str(e)}", exc_info=True)
        return False, "", f"Error: {str(e)}"


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")


@bot.tree.command(name="help", description="Show help for all commands")
async def help_command(interaction: discord.Interaction):
    """Display help information for all available commands"""
    await interaction.response.defer()
    
    embed = discord.Embed(
        title="🎀 Gestor de Cuentas Shizuku - Ayuda",
        color=0xa832a8,
        description="Guía completa de todos los comandos disponibles"
    )
    
    # Account Management
    embed.add_field(
        name="📋 **Gestión de Cuentas**",
        value="`/addaccount` - Agregar una nueva cuenta Minecraft con estado opcional\n"
              "`/editaccount` - Editar los detalles de una cuenta existente\n"
              "`/getaccount` - Ver información de la cuenta, skin y cambiar estado\n"
              "`/deleteaccount` - Eliminar una cuenta de la base de datos",
        inline=False
    )
    
    # Database Management
    embed.add_field(
        name="🗄️ **Gestión de Base de Datos**",
        value="`/listaccounts` - Listar todas las cuentas organizadas por estado\n"
              "`/update` - Recargar base de datos desde archivo JSON (sincronizar cambios)",
        inline=False
    )
    
    # Viewing & Status
    embed.add_field(
        name="🎮 **Visor y Estado**",
        value="`/skinviewer` - Ver el skin de un jugador Minecraft (vistas frontal/trasera)\n"
              "\n**Opciones de Estado**: ADDED, ACTIVE, DISTRIBUTED, DUPLICATED, BLOCKED",
        inline=False
    )
    
    # Command Parameters
    embed.add_field(
        name="⚙️ **Parámetros de Comandos**",
        value="**addaccount**: `<id>` `<email>` `<password>` `<ign>` `[status]`\n"
              "**editaccount**: `<id>` `<email>` `<password>` `<ign>` `[status]`\n"
              "**getaccount**: `<id>`\n"
              "**deleteaccount**: `<id>`\n"
              "**skinviewer**: `<username>`",
        inline=False
    )
    
    # Features
    embed.add_field(
        name="✨ **Características**",
        value="✅ Verificación en tiempo real del skin desde Mojang API\n"
              "✅ Visor de skin interactivo (vistas frontal/trasera)\n"
              "✅ Gestión de estado de un clic (Activo/Duplicado/Bloqueado)\n"
              "✅ Base de datos JSON local con registro automático\n"
              "✅ Detección de cuenta premium\n"
              "✅ Protección de limitación de velocidad",
        inline=False
    )
    
    # Examples
    embed.add_field(
        name="📝 **Ejemplos**",
        value="`/addaccount id:1 email:user@mail.com password:pass123 ign:PlayerName status:ACTIVE`\n"
              "`/getaccount id:1`\n"
              "`/editaccount id:1 email:new@mail.com password:newpass ign:NewName`\n"
              "`/skinviewer username:PlayerName`",
        inline=False
    )
    
    # Footer
    embed.set_footer(text="🎀 Shizuku | Creado para Gestión de Cuentas Minecraft", icon_url=None)
    embed.timestamp = discord.utils.utcnow()
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="addaccount", description="Add a new Minecraft account")
@app_commands.describe(
    account_id="Unique identifier for the account",
    email="Email address for the account",
    password="Password for the account",
    ign="In-game name (Minecraft username)",
    status="Account status (ADDED, ACTIVE, DISTRIBUTED, DUPLICATED, BLOCKED)"
)
async def add_account(interaction: discord.Interaction, account_id: str, email: str, password: str, ign: str, status: str = None):
    """Add a new account to the database"""
    await interaction.response.defer()
    
    # Validate status if provided
    valid_statuses = ["ADDED", "ACTIVE", "DISTRIBUTED", "DUPLICATED", "BLOCKED"]
    if status and status.upper() not in valid_statuses:
        invalid_status = "Invalid status"
        embed = create_error_embed("Error", invalid_status)
        await interaction.followup.send(embed=embed)
        return
    
    # Verify if the IGN has a real Minecraft skin
    has_skin, uuid, skin_message = await verify_minecraft_skin(ign)
    
    if not has_skin:
        embed = create_error_embed("Cuenta Minecraft Inválida", f"❌ {skin_message}\n\nEl IGN `{ign}` no tiene una cuenta Minecraft válida o skin.")
        await interaction.followup.send(embed=embed)
        return
    
    # Add account to database
    success, message = DatabaseManager.add_account(account_id, email, password, ign)
    
    if success:
        # Update status if provided
        if status:
            database = DatabaseManager._load_database()
            for acc in database["accounts"]:
                if acc["id"] == account_id:
                    acc['status'] = status.upper()
                    break
            DatabaseManager._save_database(database)
            DatabaseManager._log_action(status.upper(), {"ign": ign, "email": email, "password": password})
        
        embed = create_success_embed("Cuenta Agregada", f"✅ {message}\n✅ {skin_message}")
        account = DatabaseManager.get_account(account_id)
        if account:
            embed_info = create_account_embed(account, color=0x00FF00)
            embed_info.set_thumbnail(url=f"https://skins.mcstats.com/head/{uuid}")
            
            # Create skin viewer with buttons
            skin_embed = create_skin_embed(uuid, "front")
            view = SkinViewButtons(uuid, ign, interaction.user.id, embed_info)
            
            await interaction.followup.send(embeds=[embed, embed_info, skin_embed], view=view)
    else:
        embed = create_error_embed("Error al Agregar Cuenta", message)
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="editaccount", description="Edit an existing Minecraft account")
@app_commands.describe(
    account_id="Unique identifier for the account",
    email="New email address for the account",
    password="New password for the account",
    ign="New in-game name (Minecraft username)",
    status="Account status (ADDED or DISTRIBUTED)"
)
async def edit_account(interaction: discord.Interaction, account_id: str, email: str, password: str, ign: str, status: str = None):
    """Edit an existing account in the database"""
    await interaction.response.defer()
    
    # Check if account exists first
    existing_account = DatabaseManager.get_account(account_id)
    if not existing_account:
        embed = create_error_embed("Cuenta No Encontrada", f"¡La cuenta con ID `{account_id}` no existe!")
        await interaction.followup.send(embed=embed)
        return
    
    # Validate status if provided
    if status and status.upper() not in ["ADDED", "DISTRIBUTED"]:
        embed = create_error_embed("Estado Inválido", "El estado debe ser `ADDED` o `DISTRIBUTED`")
        await interaction.followup.send(embed=embed)
        return
    
    # Edit account
    success, message = DatabaseManager.edit_account(account_id, email, password, ign)
    
    if success:
        # Update status if provided
        if status:
            account = DatabaseManager.get_account(account_id)
            if account:
                account['status'] = status.upper()
                database = DatabaseManager._load_database()
                for acc in database["accounts"]:
                    if acc["id"] == account_id:
                        acc['status'] = status.upper()
                        break
                DatabaseManager._save_database(database)
                DatabaseManager._log_action(status.upper(), {"ign": ign, "email": email, "password": password})
        
        embed = create_success_embed("Cuenta Editada", message)
        account = DatabaseManager.get_account(account_id)
        if account:
            embed_info = create_account_embed(account, color=0x00FF00)
            await interaction.followup.send(embeds=[embed, embed_info])
    else:
        embed = create_error_embed("Error al Editar Cuenta", message)
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="update", description="Reload the bot database from JSON file")
async def update_database(interaction: discord.Interaction):
    """Reload the bot database from the JSON file (syncs changes made directly to accounts.json)"""
    await interaction.response.defer()
    user_id = interaction.user.id
    
    try:
        # Reload database from JSON file
        database = DatabaseManager._load_database()
        accounts = database.get("accounts", [])
        
        # Count accounts by status
        status_counts = {
            'ACTIVE': 0,
            'DISTRIBUTED': 0,
            'DUPLICATED': 0,
            'BLOCKED': 0,
            'ADDED': 0
        }
        
        for account in accounts:
            status = account.get('status', 'ADDED')
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts['ADDED'] += 1
        
        # Create success embed
        description = "✅ ¡Base de datos recargada exitosamente!\n\n"
        description += "**Cuentas cargadas:**\n"
        
        for status, count in status_counts.items():
            if count > 0:
                description += f"• {status}: `{count}`\n"
        
        description += f"\n**Total**: `{len(accounts)}`"
        
        embed = create_success_embed("Base de Datos Actualizada", description)
        await interaction.followup.send(embed=embed)
        
        logger.info(f"Database reloaded from JSON file. Total accounts: {len(accounts)}")
        
    except Exception as e:
        logger.error(f"Error reloading database: {e}")
        embed = create_error_embed("Error al Recargar Base de Datos", f"Error al recargar la base de datos: {str(e)}")
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="getaccount", description="Get account information by ID")
@app_commands.describe(
    account_id="Unique identifier for the account"
)
async def get_account(interaction: discord.Interaction, account_id: str):
    """Retrieve account information with skin viewer and status buttons"""
    await interaction.response.defer()
    user_id = interaction.user.id
    
    account = DatabaseManager.get_account(account_id)
    
    if account:
        # Verify skin and get UUID
        has_skin, uuid, skin_message = await verify_minecraft_skin(account['ign'])
        
        # Create combined embed
        embed = create_account_embed(account)
        
        # Add skin thumbnail if available
        if has_skin:
            embed.set_thumbnail(url=f"https://skins.mcstats.com/head/{uuid}")
            
            # Create skin viewer with buttons and status buttons in one view
            skin_embed = create_skin_embed(uuid, "front")
            
            # Combine both views
            class CombinedView(discord.ui.View):
                def __init__(self, uuid, ign, user_id, account_id, timeout=300):
                    super().__init__(timeout=timeout)
                    self.uuid = uuid
                    self.ign = ign
                    self.user_id = user_id
                    self.account_id = account_id
                    self.current_view = "front"
                    self.current_embed = None  # Store current embed
                
                @discord.ui.button(label="Front View", emoji="🈹", style=discord.ButtonStyle.secondary)
                async def front_view(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                        return
                    self.current_view = "front"
                    skin_embed = create_skin_embed(self.uuid, "front")
                    await interaction.response.edit_message(embeds=[self.current_embed, skin_embed], view=self)
                
                @discord.ui.button(label="Back View", emoji="🈹", style=discord.ButtonStyle.secondary)
                async def back_view(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                        return
                    self.current_view = "back"
                    skin_embed = create_skin_embed(self.uuid, "back")
                    await interaction.response.edit_message(embeds=[self.current_embed, skin_embed], view=self)
                
                @discord.ui.button(label="Active", emoji="🟢", style=discord.ButtonStyle.success)
                async def active_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                        return
                    await self._update_status(interaction, "ACTIVE")
                
                @discord.ui.button(label="Duplicated", emoji="📋", style=discord.ButtonStyle.secondary)
                async def duplicated_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                        return
                    await self._update_status(interaction, "DUPLICATED")
                
                @discord.ui.button(label="Blocked", emoji="🚫", style=discord.ButtonStyle.danger)
                async def blocked_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                        return
                    await self._update_status(interaction, "BLOCKED")
                
                async def _update_status(self, interaction: discord.Interaction, new_status: str):
                    try:
                        database = DatabaseManager._load_database()
                        for acc in database["accounts"]:
                            if acc["id"] == self.account_id:
                                acc['status'] = new_status
                                break
                        DatabaseManager._save_database(database)
                        updated_account = DatabaseManager.get_account(self.account_id)
                        DatabaseManager._log_action(new_status, {"ign": updated_account['ign'], "email": updated_account['email'], "password": updated_account['password']})
                        
                        # Update the current embed with new account info
                        self.current_embed = create_account_embed(updated_account)
                        self.current_embed.set_thumbnail(url=f"https://skins.mcstats.com/head/{self.uuid}")
                        
                        # Keep the current skin view when updating status
                        skin_embed = create_skin_embed(self.uuid, self.current_view)
                        await interaction.response.edit_message(embeds=[self.current_embed, skin_embed], view=self)
                    except Exception as e:
                        logger.error(f"Error updating status: {e}")
                        await interaction.response.send_message(f"Error updating status: {str(e)}", ephemeral=True)
            
            view = CombinedView(uuid, account['ign'], user_id, account_id)
            view.current_embed = embed  # Set the initial embed
            await interaction.followup.send(embeds=[embed, skin_embed], view=view)
        else:
            # Create status buttons only view if no skin
            status_view = StatusChangeButtons(account_id, user_id)
            await interaction.followup.send(embed=embed, view=status_view)
    else:
        embed = create_error_embed("Cuenta No Encontrada", f"¡La cuenta con ID `{account_id}` no existe!")
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="listaccounts", description="List all accounts in the database")
async def list_accounts(interaction: discord.Interaction):
    """List all accounts"""
    await interaction.response.defer()
    user_id = interaction.user.id
    
    accounts = DatabaseManager.get_all_accounts()
    
    if not accounts:
        embed = create_info_embed("Sin Cuentas", "La base de datos está vacía. Agrega una cuenta usando `/addaccount`")
        await interaction.followup.send(embed=embed)
        return
    
    # Organize accounts by status
    status_groups = {
        'ACTIVE': [],
        'DISTRIBUTED': [],
        'DUPLICATED': [],
        'BLOCKED': [],
        'ADDED': []
    }
    
    for account in accounts:
        status = account.get('status', 'ADDED')
        if status in status_groups:
            status_groups[status].append(account)
        else:
            status_groups['ADDED'].append(account)
    
    # Build pages - each page shows accounts organized by status
    pages = []
    ACCOUNTS_PER_PAGE = 10
    
    # Flatten accounts into list
    flat_accounts = []
    for status in ['ACTIVE', 'DISTRIBUTED', 'DUPLICATED', 'BLOCKED', 'ADDED']:
        flat_accounts.extend(status_groups[status])
    
    # Create pages
    for i in range(0, len(flat_accounts), ACCOUNTS_PER_PAGE):
        page_accounts = flat_accounts[i:i + ACCOUNTS_PER_PAGE]
        
        embed = discord.Embed(
            title="🎀 Gestor de Cuentas Shizuku 🎀",
            color=0xa832a8,
            description="━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                       f"**📊 Total de Cuentas**: `{len(accounts)}`\n"
                       "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        # Status emojis
        status_emojis = {
            'ACTIVE': '🟢',
            'DISTRIBUTED': '✅',
            'DUPLICATED': '📋',
            'BLOCKED': '🚫',
            'ADDED': '➕'
        }
        
        # Organize page accounts by status
        page_status_groups = {
            'ACTIVE': [],
            'DISTRIBUTED': [],
            'DUPLICATED': [],
            'BLOCKED': [],
            'ADDED': []
        }
        
        for account in page_accounts:
            status = account.get('status', 'ADDED')
            if status in page_status_groups:
                page_status_groups[status].append(account)
            else:
                page_status_groups['ADDED'].append(account)
        
        # Add sections for each status
        for status in ['ACTIVE', 'DISTRIBUTED', 'DUPLICATED', 'BLOCKED', 'ADDED']:
            accounts_list = page_status_groups[status]
            if accounts_list:
                emoji = status_emojis.get(status, '❓')
                accounts_info = []
                
                for account in accounts_list:
                    accounts_info.append(
                        f"├ {account['ign']}\n"
                        f"│ ├ 🆔 {account['id']}\n"
                        f"│ ├ 📧 {account['email']}\n"
                        f"│ └ 🔐 {account['password']}"
                    )
                
                field_value = "\n".join(accounts_info)
                embed.add_field(
                    name=f"{emoji} {status} ({len(accounts_list)})",
                    value=f"```\n{field_value}\n```",
                    inline=False
                )
        
        # Add page number footer
        total_pages = (len(flat_accounts) + ACCOUNTS_PER_PAGE - 1) // ACCOUNTS_PER_PAGE
        embed.set_footer(text=f"🎀 Shizuku | Página {len(pages) + 1}/{total_pages}", icon_url=None)
        embed.timestamp = discord.utils.utcnow()
        
        pages.append(embed)
    
    # Create pagination view if there are multiple pages
    if len(pages) > 1:
        class PaginationView(discord.ui.View):
            def __init__(self, pages, timeout=300):
                super().__init__(timeout=timeout)
                self.pages = pages
                self.current_page = 0
            
            @discord.ui.button(label="<<", style=discord.ButtonStyle.secondary, custom_id="first_page")
            async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page = 0
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
            
            @discord.ui.button(label="<", style=discord.ButtonStyle.secondary, custom_id="prev_page")
            async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page > 0:
                    self.current_page -= 1
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
            
            @discord.ui.button(label=">", style=discord.ButtonStyle.secondary, custom_id="next_page")
            async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.current_page < len(self.pages) - 1:
                    self.current_page += 1
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
            
            @discord.ui.button(label=">>", style=discord.ButtonStyle.secondary, custom_id="last_page")
            async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.current_page = len(self.pages) - 1
                await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        
        view = PaginationView(pages)
        await interaction.followup.send(embed=pages[0], view=view)
    else:
        await interaction.followup.send(embed=pages[0])


@bot.tree.command(name="deleteaccount", description="Delete an account by ID")
@app_commands.describe(
    account_id="Unique identifier for the account"
)
async def delete_account(interaction: discord.Interaction, account_id: str):
    """Delete an account from the database"""
    await interaction.response.defer()
    user_id = interaction.user.id
    
    # Check if account exists
    existing_account = DatabaseManager.get_account(account_id)
    if not existing_account:
        embed = create_error_embed("Cuenta No Encontrada", f"¡La cuenta con ID `{account_id}` no existe!")
        await interaction.followup.send(embed=embed)
        return
    
    # Delete account
    success, message = DatabaseManager.delete_account(account_id)
    
    if success:
        embed = create_success_embed("Cuenta Eliminada", message)
        await interaction.followup.send(embed=embed)
    else:
        embed = create_error_embed("Error al Eliminar Cuenta", message)
        await interaction.followup.send(embed=embed)


class StatusChangeButtons(discord.ui.View):
    """Custom view for changing account status"""
    
    def __init__(self, account_id: str, user_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.account_id = account_id
        self.user_id = user_id
    
    @discord.ui.button(label="Active", emoji="🟢", style=discord.ButtonStyle.success, custom_id="status_active")
    async def active_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return
        
        await self._update_status(interaction, "ACTIVE")
    
    @discord.ui.button(label="Duplicated", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="status_duplicated")
    async def duplicated_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return
        
        await self._update_status(interaction, "DUPLICATED")
    
    @discord.ui.button(label="Blocked", emoji="🚫", style=discord.ButtonStyle.danger, custom_id="status_blocked")
    async def blocked_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return
        
        await self._update_status(interaction, "BLOCKED")
    
    async def _update_status(self, interaction: discord.Interaction, new_status: str):
        """Update account status"""
        try:
            account = DatabaseManager.get_account(self.account_id)
            if not account:
                await interaction.response.send_message("Account not found.", ephemeral=True)
                return
            
            # Update in database
            database = DatabaseManager._load_database()
            for acc in database["accounts"]:
                if acc["id"] == self.account_id:
                    acc['status'] = new_status
                    break
            DatabaseManager._save_database(database)
            DatabaseManager._log_action(new_status, {"ign": account['ign'], "email": account['email'], "password": account['password']})
            
            # Update embed
            updated_account = DatabaseManager.get_account(self.account_id)
            embed = create_account_embed(updated_account, color=0x00FF00)
            
            await interaction.response.edit_message(embed=embed)
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            await interaction.response.send_message(f"Error updating status: {str(e)}", ephemeral=True)


class SkinViewButtons(discord.ui.View):
    """Custom view for skin viewer buttons"""
    
    def __init__(self, player_uuid: str, player_name: str, user_id: int, account_embed: discord.Embed = None, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.player_uuid = player_uuid
        self.player_name = player_name
        self.user_id = user_id
        self.account_embed = account_embed
        self.current_view = "front"
    
    @discord.ui.button(label="Front View", emoji="🈹", style=discord.ButtonStyle.secondary, custom_id="front_view")
    async def front_view_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return
        
        self.current_view = "front"
        skin_embed = create_skin_embed(self.player_uuid, "front")
        
        if self.account_embed:
            await interaction.response.edit_message(embeds=[self.account_embed, skin_embed], view=self)
        else:
            await interaction.response.edit_message(embeds=[skin_embed], view=self)
    
    @discord.ui.button(label="Back View", emoji="🈹", style=discord.ButtonStyle.secondary, custom_id="back_view")
    async def back_view_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return
        
        self.current_view = "back"
        skin_embed = create_skin_embed(self.player_uuid, "back")
        
        if self.account_embed:
            await interaction.response.edit_message(embeds=[self.account_embed, skin_embed], view=self)
        else:
            await interaction.response.edit_message(embeds=[skin_embed], view=self)
    
    async def on_timeout(self):
        # Disable buttons after timeout
        for item in self.children:
            item.disabled = True


@bot.tree.command(name="skinviewer", description="View a Minecraft player's skin")
@app_commands.describe(
    username="Minecraft player username (IGN)"
)
async def skin_viewer(interaction: discord.Interaction, username: str):
    """View a Minecraft player's skin with front and back views"""
    await interaction.response.defer()
    user_id = interaction.user.id
    
    try:
        logger.info(f"Skin viewer requested for: {username}")
        
        # Get player info from Mojang API
        player_info = await MinecraftApiService.get_player_info(username)
        
        if not player_info:
            embed = create_error_embed("Jugador No Encontrado", f"No se pudo encontrar al jugador `{username}`")
            await interaction.followup.send(embed=embed)
            return
        
        player_uuid = player_info.get('id')
        player_name = player_info.get('name', username)
        
        if not player_uuid:
            embed = create_error_embed("Error", "No se pudo recuperar el UUID del jugador")
            await interaction.followup.send(embed=embed)
            return
        
        logger.info(f"Found player: {player_name} ({player_uuid})")
        
        # Create embeds
        info_embed = create_skin_info_embed(player_name, player_uuid)
        skin_embed = create_skin_embed(player_uuid, "front")
        
        # Create view with buttons
        view = SkinViewButtons(player_uuid, player_name, user_id)
        
        # Create NameMC button
        namemc_button = discord.ui.Button(
            label="NameMC 🎀",
            url=f"https://namemc.com/profile/{player_uuid}",
            style=discord.ButtonStyle.link
        )
        view.add_item(namemc_button)
        
        # Send message
        await interaction.followup.send(embeds=[info_embed, skin_embed], view=view)
        
    except Exception as e:
        logger.error(f"Error in skin viewer: {str(e)}", exc_info=True)
        embed = create_error_embed("Error", f"Hubo un error al obtener el skin: {str(e)}")
        await interaction.followup.send(embed=embed)


# Run the bot
if __name__ == "__main__":
    import asyncio
    
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file!")
        exit(1)
    
    bot.run(DISCORD_TOKEN)
