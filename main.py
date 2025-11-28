# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
import random
import string
import re

# --- Configuración Inicial ---
TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
DISTRIBUTION_INTERVAL_MINUTES = 10.0

# *** CORREGIDO: Canal separado para solicitudes de Admins ***
try:
    REQUESTS_CHANNEL_ID = int(os.environ['REQUESTS_CHANNEL_ID'])
except (KeyError, ValueError):
    REQUESTS_CHANNEL_ID = None
    print("❌ REQUESTS_CHANNEL_ID no configurado o inválido")

# --- Rutas de Archivos ---
DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')
KEYS_FILE = os.path.join(DATA_DIR, 'keys.json')

# Asegurarse de que las carpetas y archivos existan
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

for file_path in [ACCOUNTS_FILE, LOGS_FILE, KEYS_FILE]:
    if not os.path.exists(file_path):
        if file_path.endswith('.json'):
            if file_path == KEYS_FILE:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'keys': {}, 'users_with_access': []}, f, indent=4)
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'available': [], 'distributed': []}, f, indent=4)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('--- Archivo de Registro de Cuentas ---\n')

# --- Definición del Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cargar los datos de las cuentas al iniciar
accounts_data = {'available': [], 'distributed': []}
registered_emails = set()
keys_data = {'keys': {}, 'users_with_access': []}

# --- Funciones Auxiliares ---

def load_accounts():
    """Carga los datos de las cuentas desde el archivo JSON y actualiza el conjunto de emails registrados."""
    global accounts_data, registered_emails
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'available' in data and 'distributed' in data:
                accounts_data = data
                registered_emails.clear()
                for account in accounts_data['distributed']:
                    if 'gmail' in account:
                        registered_emails.add(account['gmail'].lower())
                for account in accounts_data['available']:
                    if 'gmail' in account:
                        registered_emails.add(account['gmail'].lower())
                return True
            else:
                return False
    except:
        return False

def save_accounts():
    """Guarda los datos de las cuentas en el archivo JSON."""
    try:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts_data, f, indent=4)
    except Exception as e:
        print(f"Error guardando cuentas: {e}")

def load_keys():
    """Carga los datos de keys y acceso."""
    global keys_data
    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            keys_data = json.load(f)
            clean_expired_keys()
            return True
    except:
        return False

def save_keys():
    """Guarda los datos de keys y acceso."""
    try:
        with open(KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys_data, f, indent=4)
    except Exception as e:
        print(f"Error guardando keys: {e}")

def update_log(account_info, status):
    """Añade una entrada al archivo de registro (log)."""
    log_entry = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"STATUS: {status} | Email: {account_info['gmail']} | Pass: {account_info['password']}\n"
    )
    try:
        with open(LOGS_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Error escribiendo log: {e}")

def remove_import_file(file_path):
    """Elimina el archivo de importación de cuentas."""
    try:
        os.remove(file_path)
        print(f"Archivo de importación eliminado: {file_path}")
    except Exception as e:
        print(f"Error al eliminar archivo {file_path}: {e}")

def generate_key():
    """Genera una key en formato HMFB-XXXX-XXXX-XXXX"""
    parts = []
    parts.append("HMFB")
    for _ in range(3):
        part = ''.join(random.choices(string.digits, k=4))
        parts.append(part)
    return '-'.join(parts)

def has_access(user_id):
    """Verifica si un usuario tiene acceso al comando /cuenta"""
    return user_id in keys_data['users_with_access']

def clean_expired_keys():
    """Limpia las keys expiradas del sistema."""
    now = datetime.now()
    expired_keys = []
    
    for key, key_data in keys_data['keys'].items():
        if 'expires_at' in key_data:
            expires_at = datetime.fromisoformat(key_data['expires_at'])
            if now > expires_at:
                expired_keys.append(key)
    
    for key in expired_keys:
        del keys_data['keys'][key]
        print(f"🗑️ Key expirada eliminada: {key}")
    
    if expired_keys:
        save_keys()

def parse_time_string(time_str):
    """
    Convierte strings como '6s', '6m', '6h', '6d' a segundos
    Retorna: (segundos_totales, texto_legible)
    """
    if not time_str or time_str.lower() == 'permanent':
        return 0, "Permanente"
    
    units = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
    }
    
    total_seconds = 0
    time_parts = []
    
    matches = re.findall(r'(\d+)([smhd])', time_str.lower())
    
    if not matches:
        raise ValueError("Formato de tiempo inválido")
    
    for number, unit in matches:
        number = int(number)
        seconds = number * units[unit]
        total_seconds += seconds
        
        if unit == 's':
            time_parts.append(f"{number} segundo{'s' if number != 1 else ''}")
        elif unit == 'm':
            time_parts.append(f"{number} minuto{'s' if number != 1 else ''}")
        elif unit == 'h':
            time_parts.append(f"{number} hora{'s' if number != 1 else ''}")
        elif unit == 'd':
            time_parts.append(f"{number} día{'s' if number != 1 else ''}")
    
    readable_time = ", ".join(time_parts)
    return total_seconds, readable_time

# *** Tarea para limpiar keys expiradas periódicamente ***
@tasks.loop(hours=1)
async def clean_keys_task():
    """Limpia keys expiradas cada hora."""
    clean_expired_keys()

# *** NUEVO: View para borrar tickets ***
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🗑️ Borrar Ticket', style=discord.ButtonStyle.danger, custom_id='delete_ticket')
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verificar que sea un administrador o el usuario del ticket
        user_has_permission = (
            interaction.user.guild_permissions.administrator or 
            interaction.user.name in interaction.channel.name
        )
        
        if not user_has_permission:
            await interaction.response.send_message(
                '❌ Solo los administradores o el dueño del ticket pueden borrarlo.',
                ephemeral=True
            )
            return
        
        # Confirmar eliminación
        confirm_embed = discord.Embed(
            title='⚠️ Confirmar Eliminación',
            description='¿Estás seguro de que quieres eliminar este ticket? Esta acción no se puede deshacer.',
            color=discord.Color.orange()
        )
        
        confirm_view = discord.ui.View(timeout=30)
        
        @discord.ui.button(label='✅ Sí, Eliminar', style=discord.ButtonStyle.danger)
        async def confirm_delete(interaction: discord.Interaction, button: discord.ui.Button):
            try:
                channel_name = interaction.channel.name
                await interaction.response.send_message('🗑️ Eliminando ticket...', ephemeral=True)
                await interaction.channel.delete(reason=f'Ticket eliminado por {interaction.user.name}')
                print(f"🗑️ Ticket eliminado: {channel_name} por {interaction.user.name}")
            except Exception as e:
                await interaction.response.send_message(f'❌ Error al eliminar el ticket: {e}', ephemeral=True)
        
        @discord.ui.button(label='❌ Cancelar', style=discord.ButtonStyle.secondary)
        async def cancel_delete(interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message('✅ Eliminación cancelada.', ephemeral=True)
        
        confirm_view.add_item(confirm_delete)
        confirm_view.add_item(cancel_delete)
        
        await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)

# *** Clase Modal para /get-key ***
class KeyRequestModal(discord.ui.Modal, title='Solicitud de Key de Acceso'):
    def __init__(self, bot_instance):
        super().__init__(timeout=300)
        self.bot = bot_instance
    
    name = discord.ui.TextInput(
        label='Nombre Completo',
        placeholder='Ingresa tu nombre y apellido',
        required=True,
        max_length=100
    )
    
    reason = discord.ui.TextInput(
        label='Razón de la Solicitud',
        placeholder='Explica detalladamente por qué necesitas acceso a las cuentas',
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not REQUESTS_CHANNEL_ID:
            await interaction.response.send_message(
                '❌ El sistema de solicitudes no está configurado correctamente.',
                ephemeral=True
            )
            return

        requests_channel = self.bot.get_channel(REQUESTS_CHANNEL_ID)
        if not requests_channel:
            await interaction.response.send_message(
                '❌ No se pudo encontrar el canal de solicitudes de administradores.',
                ephemeral=True
            )
            return

        try:
            embed = discord.Embed(
                title='🔑 Nueva Solicitud de Key - PENDIENTE',
                description=f'Solicitud de key de {interaction.user.mention}',
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            embed.add_field(name='👤 Nombre', value=self.name.value, inline=False)
            embed.add_field(name='📝 Razón', value=self.reason.value, inline=False)
            embed.add_field(name='🆔 User ID', value=interaction.user.id, inline=True)
            embed.add_field(name='📅 Fecha', value=f"<t:{int(datetime.now().timestamp())}:F>", inline=True)
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            embed.set_footer(text='Usa los botones de abajo para aceptar o rechazar la solicitud')
            
            view = KeyRequestView(interaction.user.id, self.name.value, self.reason.value)
            
            await requests_channel.send(embed=embed, view=view)
            
            await interaction.response.send_message(
                '✅ Tu solicitud ha sido enviada correctamente a los administradores. '
                'Te notificaremos cuando sea revisada.',
                ephemeral=True
            )
            
            print(f"📨 Nueva solicitud de key enviada por {interaction.user.name} al canal {REQUESTS_CHANNEL_ID}")
            
        except discord.Forbidden:
            await interaction.response.send_message(
                '❌ Error: No tengo permisos para enviar mensajes al canal de solicitudes.',
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f'❌ Error al enviar la solicitud: {str(e)}',
                ephemeral=True
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            '❌ Ocurrió un error al procesar tu solicitud. Por favor, intenta nuevamente.',
            ephemeral=True
        )
        print(f"Error en modal de key request: {error}")

# *** View para los botones de aceptar/rechazar ***
class KeyRequestView(discord.ui.View):
    def __init__(self, user_id, user_name, user_reason):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.user_name = user_name
        self.user_reason = user_reason
    
    @discord.ui.button(label='Aceptar', style=discord.ButtonStyle.success, custom_id='accept_key')
    async def accept_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Solo los administradores pueden usar este botón.', ephemeral=True)
            return

        user = interaction.guild.get_member(self.user_id)
        if user:
            try:
                # Crear canal privado (ticket)
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                
                # Añadir permisos para administradores
                for role in interaction.guild.roles:
                    if role.permissions.administrator:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                
                channel = await interaction.guild.create_text_channel(
                    f'ticket-{user.display_name}',
                    overwrites=overwrites,
                    reason=f'Ticket para key request de {user.display_name}'
                )
                
                # Enviar mensaje en el ticket CON BOTÓN DE BORRAR
                embed = discord.Embed(
                    title='🎫 Ticket de Key Aceptado',
                    description=f'Hola {user.mention}, tu solicitud de key ha sido **aceptada**.',
                    color=discord.Color.green()
                )
                embed.add_field(name='👤 Nombre', value=self.user_name, inline=False)
                embed.add_field(name='📝 Razón', value=self.user_reason, inline=False)
                embed.add_field(name='✅ Aceptado por', value=interaction.user.mention, inline=False)
                embed.add_field(name='🔑 Próximos pasos', value='Un administrador te proporcionará una key pronto.', inline=False)
                embed.add_field(name='🗑️ Gestión', value='Usa el botón de abajo para eliminar este ticket cuando hayas terminado.', inline=False)
                
                # *** NUEVO: Añadir view con botón de borrar ticket ***
                ticket_view = TicketView()
                await channel.send(embed=embed, view=ticket_view)
                
                await interaction.response.send_message(f'✅ Ticket creado: {channel.mention}', ephemeral=True)
                
                # Actualizar el embed original en el canal de solicitudes
                embed_original = interaction.message.embeds[0]
                embed_original.title = '🔑 Solicitud de Key - ACEPTADA ✅'
                embed_original.color = discord.Color.green()
                embed_original.add_field(name='📊 Estado', value='✅ ACEPTADA', inline=False)
                embed_original.add_field(name='👤 Aceptado por', value=interaction.user.mention, inline=False)
                embed_original.add_field(name='🎫 Ticket', value=channel.mention, inline=False)
                
                # Deshabilitar botones
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(embed=embed_original, view=self)
                
            except Exception as e:
                await interaction.response.send_message(f'❌ Error al crear ticket: {e}', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Usuario no encontrado en el servidor', ephemeral=True)
    
    @discord.ui.button(label='Rechazar', style=discord.ButtonStyle.danger, custom_id='reject_key')
    async def reject_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Solo los administradores pueden usar este botón.', ephemeral=True)
            return

        user = interaction.guild.get_member(self.user_id)
        if user:
            try:
                embed = discord.Embed(
                    title='❌ Solicitud de Key Rechazada',
                    description='Tu solicitud de key ha sido rechazada por un administrador.',
                    color=discord.Color.red()
                )
                embed.add_field(name='👤 Nombre', value=self.user_name, inline=False)
                embed.add_field(name='📝 Razón de tu solicitud', value=self.user_reason, inline=False)
                embed.add_field(name='👤 Rechazado por', value=interaction.user.mention, inline=False)
                embed.add_field(name='ℹ️ Motivo', value='Puedes contactar a un administrador para más información.', inline=False)
                
                await user.send(embed=embed)
                await interaction.response.send_message('✅ Usuario notificado del rechazo', ephemeral=True)
                
            except:
                await interaction.response.send_message('✅ Solicitud rechazada (no se pudo notificar al usuario via DM)', ephemeral=True)
        
        embed_original = interaction.message.embeds[0]
        embed_original.title = '🔑 Solicitud de Key - RECHAZADA ❌'
        embed_original.color = discord.Color.red()
        embed_original.add_field(name='📊 Estado', value='❌ RECHAZADA', inline=False)
        embed_original.add_field(name='👤 Rechazado por', value=interaction.user.mention, inline=False)
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed_original, view=self)

# --- Tasks y Eventos ---

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f'🤖 Bot conectado como {bot.user}!')
    print(f'📊 Canal de distribución: {CHANNEL_ID}')
    print(f'📨 Canal de solicitudes (Admins): {REQUESTS_CHANNEL_ID}')
    load_accounts()
    load_keys()
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Sincronizados {len(synced)} comandos de barra")
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")
    
    distribute_account.start()
    clean_keys_task.start()

@tasks.loop(minutes=DISTRIBUTION_INTERVAL_MINUTES)
async def distribute_account():
    """Tarea de bucle para distribuir cuentas en el canal configurado."""
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    if not channel or not accounts_data['available']:
        return

    account_to_distribute = accounts_data['available'].pop(0)

    required_keys = ['gmail', 'password']
    if not all(key in account_to_distribute for key in required_keys):
        accounts_data['available'].insert(0, account_to_distribute)
        return

    embed = discord.Embed(
        title=f"✨ Cuenta Disponible | Correo: {account_to_distribute['gmail']} ✨",
        description="¡Se ha liberado una cuenta! Reacciona para indicar su estado:",
        color=discord.Color.dark_green()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=f"`{account_to_distribute['gmail']}`", inline=False)
    embed.add_field(name="🔒 Contraseña", value=f"`{account_to_distribute['password']}`", inline=False)
    embed.set_footer(text=f"Reacciona: ✅ Usada | ❌ Error Credenciales | 🚨 Cuenta No Sirve/Bloqueada | {len(accounts_data['available'])} restantes.")

    try:
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("🚨")

        account_data_distributed = account_to_distribute.copy()
        account_data_distributed['distribution_date'] = datetime.now().isoformat()
        account_data_distributed['message_id'] = message.id
        account_data_distributed['reactions'] = {'✅':0,'❌':0,'🚨':0,'users':[]}
        accounts_data['distributed'].append(account_data_distributed)
        
        save_accounts()
        update_log(account_to_distribute, "DISTRIBUTED")
        
    except:
        accounts_data['available'].insert(0, account_to_distribute)

@bot.event
async def on_reaction_add(reaction, user):
    """Maneja las reacciones a los mensajes de distribución."""
    if user.bot:
        return

    valid_emojis = ["✅","❌", "🚨"]

    if reaction.message.channel.id != CHANNEL_ID or str(reaction.emoji) not in valid_emojis:
        return

    message_id = reaction.message.id
    reacted_emoji = str(reaction.emoji)
    user_id = user.id

    for account in accounts_data['distributed']:
        if account.get('message_id') == message_id:
            if user_id in account['reactions']['users']:
                await reaction.remove(user)
                return

            account['reactions']['users'].append(user_id)
            account['reactions'][reacted_emoji] += 1
            save_accounts()
            return

# --- Comandos de Barra ---

@bot.tree.command(name="get-key", description="Solicitar una key de acceso a las cuentas")
async def get_key(interaction: discord.Interaction):
    """Comando para solicitar una key de acceso"""
    if not REQUESTS_CHANNEL_ID:
        await interaction.response.send_message(
            '❌ El sistema de solicitudes no está configurado. Contacta a un administrador.',
            ephemeral=True
        )
        return
    
    modal = KeyRequestModal(bot)
    await interaction.response.send_modal(modal)

@bot.tree.command(name="key", description="Generar una key de acceso con tiempo específico (Admin)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    tiempo="Tiempo de duración (ej: 6s, 6m, 6h, 6d, 1h30m, 2d12h) o 'permanent'"
)
async def generate_key_command(interaction: discord.Interaction, tiempo: str = "permanent"):
    """Genera una nueva key de acceso con tiempo específico"""
    new_key = generate_key()
    
    try:
        total_seconds, readable_time = parse_time_string(tiempo)
        
        expires_at = None
        if total_seconds > 0:
            expires_at = datetime.now() + timedelta(seconds=total_seconds)
        
        key_data = {
            'used': False,
            'user_id': None,
            'created_by': interaction.user.id,
            'created_at': datetime.now().isoformat(),
            'expires_at': expires_at.isoformat() if expires_at else None
        }
        
        keys_data['keys'][new_key] = key_data
        save_keys()
        
        embed = discord.Embed(
            title='🔑 Nueva Key Generada',
            description=f'**Key:** `{new_key}`',
            color=discord.Color.green()
        )
        embed.add_field(name='Creada por', value=interaction.user.mention, inline=True)
        
        if expires_at:
            embed.add_field(name='⏰ Expira', value=f'<t:{int(expires_at.timestamp())}:R>', inline=True)
            embed.add_field(name='Duración', value=readable_time, inline=True)
            embed.add_field(name='Estado', value='🟢 ACTIVA (Temporal)', inline=False)
        else:
            embed.add_field(name='⏰ Expira', value='Nunca', inline=True)
            embed.add_field(name='Estado', value='🟢 ACTIVA (Permanente)', inline=False)
        
        examples = "**Ejemplos:**\n• `/key 6h` - 6 horas\n• `/key 2d12h` - 2 días y 12 horas\n• `/key 30m` - 30 minutos\n• `/key permanent` - Permanente"
        embed.add_field(name='💡 Formatos válidos', value=examples, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except ValueError as e:
        await interaction.response.send_message(
            f'❌ Formato de tiempo inválido. Usa: `6s`, `6m`, `6h`, `6d`, `1h30m`, `2d12h` o `permanent`\n'
            f'**Ejemplos:**\n• `/key 6h` - 6 horas\n• `/key 2d12h` - 2 días y 12 horas\n• `/key 30m` - 30 minutos\n• `/key permanent` - Permanente',
            ephemeral=True
        )

@bot.tree.command(name="access", description="Validar tu key de acceso")
async def access_command(interaction: discord.Interaction, key: str):
    """Validar una key de acceso"""
    key_upper = key.upper()
    
    if key_upper in keys_data['keys']:
        key_info = keys_data['keys'][key_upper]
        
        if key_info.get('expires_at'):
            expires_at = datetime.fromisoformat(key_info['expires_at'])
            if datetime.now() > expires_at:
                await interaction.response.send_message('❌ Esta key ha expirado.', ephemeral=True)
                return
        
        if key_info['used']:
            await interaction.response.send_message('❌ Esta key ya ha sido utilizada.', ephemeral=True)
        else:
            key_info['used'] = True
            key_info['user_id'] = interaction.user.id
            key_info['used_at'] = datetime.now().isoformat()
            
            if interaction.user.id not in keys_data['users_with_access']:
                keys_data['users_with_access'].append(interaction.user.id)
            
            save_keys()
            
            embed = discord.Embed(
                title='✅ Acceso Concedido',
                description='Ahora tienes acceso al comando `/cuenta`',
                color=discord.Color.green()
            )
            
            if key_info.get('expires_at'):
                expires_at = datetime.fromisoformat(key_info['expires_at'])
                embed.add_field(name='⏰ Key expira', value=f'<t:{int(expires_at.timestamp())}:R>')
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message('❌ Key inválida.', ephemeral=True)

@bot.tree.command(name="cuenta", description="Obtener una cuenta (Requiere key)")
async def cuenta_command(interaction: discord.Interaction):
    """Obtener una cuenta del inventario"""
    if not has_access(interaction.user.id):
        await interaction.response.send_message(
            '❌ No tienes acceso a este comando. Usa `/get-key` para solicitar acceso.',
            ephemeral=True
        )
        return
    
    if not accounts_data['available']:
        await interaction.response.send_message(
            '❌ No hay cuentas disponibles en este momento.',
            ephemeral=True
        )
        return
    
    account = accounts_data['available'].pop(0)
    save_accounts()
    
    try:
        embed = discord.Embed(
            title='📧 Cuenta Obtenida',
            description='Aquí tienes tu cuenta:',
            color=discord.Color.blue()
        )
        embed.add_field(name='📧 Correo', value=f'`{account["gmail"]}`', inline=False)
        embed.add_field(name='🔒 Contraseña', value=f'`{account["password"]}`', inline=False)
        embed.set_footer(text='¡Disfruta tu cuenta!')
        
        await interaction.user.send(embed=embed)
        await interaction.response.send_message(
            '✅ Tu cuenta ha sido enviada por mensaje privado.',
            ephemeral=True
        )
        
        update_log(account, "CLAIMED")
        
    except discord.Forbidden:
        await interaction.response.send_message(
            '❌ No puedo enviarte mensajes privados. Activa tus DMs y vuelve a intentarlo.',
            ephemeral=True
        )
        accounts_data['available'].insert(0, account)
        save_accounts()

# --- Comandos de Prefijo ---

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    email_lower = email.lower()

    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta con correo **{email}** ya existe en el inventario.")
        return

    await ctx.send("✅ Recibida la información.")

    new_account = {'username':email,'gmail':email,'password':password}
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower)
    save_accounts()
    update_log(new_account,"ADDED")

    embed = discord.Embed(
        title="✅ Cuenta Añadida",
        description="La cuenta ha sido añadida al inventario y está lista para ser distribuida.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=email)
    embed.add_field(name="🔒 Contraseña", value=password)
    embed.add_field(name="Inventario Total", value=f"{len(accounts_data['available'])} disponibles")
    await ctx.send(embed=embed)

@bot.command(name='importaccounts', help='Importa varias cuentas desde archivo import_accounts.txt con formato: correo:contraseña')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        await ctx.send(f"❌ No se encontró el archivo {file_path}. Asegúrate de crearlo con formato `correo:contraseña` por línea.")
        return

    await ctx.send("⏳ Importando cuentas...")
    success_count = 0
    fail_count = 0
    duplicate_count = 0

    remaining_lines = [] 

    with open(file_path,'r',encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue

        if stripped_line.count(":") != 1: 
            remaining_lines.append(line)
            fail_count += 1
            continue

        try:
            email, password = stripped_line.split(":", 1)
            email_lower = email.lower()

            if email_lower in registered_emails:
                duplicate_count += 1
                continue
            
            new_account = {'username':email,'gmail':email,'password':password}
            accounts_data['available'].append(new_account)
            registered_emails.add(email_lower)
            update_log(new_account,"ADDED")
            success_count += 1

        except Exception as e:
            remaining_lines.append(line) 
            print(f"Error procesando línea en import: {line}. Error: {e}")
            fail_count += 1

    save_accounts()

    if remaining_lines:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(remaining_lines) + '\n')
        await ctx.send(f"⚠️ **{fail_count}** líneas con formato incorrecto. Quedan en `{file_path}` para corrección.")
    else:
        remove_import_file(file_path)
    
    await ctx.send(
        f"✅ Importadas **{success_count}** cuentas correctamente.\n"
        f"🔄 Duplicadas (ya en inventario): **{duplicate_count}** (omitidas).\n"
        f"❌ Fallidas (formato incorrecto): **{fail_count}**."
    )

@add_account.error
async def add_account_error(ctx,error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorrecto: `!addaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado. Solo administradores pueden usar este comando.")
    else:
        print(f"Error inesperado en add_account: {error}")
        await ctx.send("❌ Error al añadir la cuenta. Revisa la consola para más detalles.")

# --- Comando Sync ---
@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sincronizados {len(synced)} comandos de barra")
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        await ctx.send(f"❌ Error sincronizando comandos: {e}")
        print(f"Error sincronizando: {e}")

# --- Keep Alive ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is running and ready!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- Ejecución Final ---
if __name__ == '__main__':
    keep_alive()
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("*** ERROR: Token de Discord inválido ***")
    except Exception as e:
        print(f"*** ERROR FATAL: {e} ***")
