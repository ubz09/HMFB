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
DISTRIBUTION_INTERVAL_MINUTES = 60.0

# *** CORREGIDO: Canal separado para solicitudes de Admins ***
try:
    REQUESTS_CHANNEL_ID = int(os.environ['REQUESTS_CHANNEL_ID'])
except (KeyError, ValueError):
    REQUESTS_CHANNEL_ID = None
    print("❌ REQUESTS_CHANNEL_ID no configurado o inválido")

# --- Configuración de Verificación y Roles ---
try:
    VERIFICATION_CHANNEL_ID = int(os.environ['VERIFICATION_CHANNEL_ID'])
    VERIFICATION_ROLE_ID = int(os.environ['VERIFICATION_ROLE_ID'])
    VERIFICATION_EMOJI = os.environ.get('VERIFICATION_EMOJI', '✅')
    VERIFICATION_IMAGE_URL = os.environ.get('VERIFICATION_IMAGE_URL', '')
except (KeyError, ValueError):
    VERIFICATION_CHANNEL_ID = 1444476201270771843
    VERIFICATION_ROLE_ID = 1444480681991471204
    VERIFICATION_EMOJI = '✅'
    VERIFICATION_IMAGE_URL = 'https://media.discordapp.net/attachments/1444072962729840722/1444089581128384522/pe.webp?ex=692cc23a&is=692b70ba&hm=a019c6f38ca3b57dd320ae272bc23a741e5dd268175b03f2eb74e9eef8b4ced0&=&format=webp&width=300&height=300'
    print("❌ Configuración de verificación no encontrada")

# --- Rutas de Archivos ---
DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')
KEYS_FILE = os.path.join(DATA_DIR, 'keys.json')
INVITES_FILE = os.path.join(DATA_DIR, 'invites.json')

# Asegurarse de que las carpetas y archivos existan
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

for file_path in [ACCOUNTS_FILE, LOGS_FILE, KEYS_FILE, INVITES_FILE]:
    if not os.path.exists(file_path):
        if file_path.endswith('.json'):
            if file_path == KEYS_FILE:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'keys': {}, 'users_with_access': []}, f, indent=4)
            elif file_path == INVITES_FILE:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'invites': {}, 'join_events': {}, 'user_invites': {}}, f, indent=4)
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
intents.invites = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Cargar los datos de las cuentas al iniciar
accounts_data = {'available': [], 'distributed': []}
registered_emails = set()
keys_data = {'keys': {}, 'users_with_access': []}

# --- Funciones Auxiliares ---

def load_invites_data():
    """Carga los datos de invitaciones desde el archivo JSON."""
    try:
        with open(INVITES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'invites': {}, 'join_events': {}, 'user_invites': {}}

def save_invites_data(data):
    """Guarda los datos de invitaciones en el archivo JSON."""
    try:
        with open(INVITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error guardando datos de invitaciones: {e}")

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

# --- Sistema de Tracking de Invitaciones ---

def analyze_user_invites(invites_data, user_id, guild):
    """Analiza las invitaciones de un usuario y las categoriza."""
    user_id_str = str(user_id)
    
    if user_id_str not in invites_data['user_invites']:
        return None
    
    user_invites = invites_data['user_invites'][user_id_str]
    total_invites = len(user_invites)
    
    # Categorías
    valid_invites = []
    fake_invites = []
    left_invites = []
    j4j_invites = []
    alt_invites = []
    
    FAKE_THRESHOLD = 5 * 60  # 5 minutos en segundos
    
    for invited_user_id, invite_data in user_invites.items():
        invited_user = guild.get_member(int(invited_user_id))
        join_time = datetime.fromisoformat(invite_data['joined_at'])
        
        # Verificar si es fake (se fue en menos de 5 minutos)
        if invite_data.get('left_at'):
            left_time = datetime.fromisoformat(invite_data['left_at'])
            time_in_server = (left_time - join_time).total_seconds()
            if time_in_server < FAKE_THRESHOLD:
                fake_invites.append({
                    'user_id': invited_user_id,
                    'username': invite_data['username'],
                    'time_in_server': time_in_server
                })
                continue
        
        # Verificar si se fue (left)
        if invite_data.get('left_at'):
            left_invites.append({
                'user_id': invited_user_id,
                'username': invite_data['username'],
                'joined_at': invite_data['joined_at'],
                'left_at': invite_data['left_at']
            })
            continue
        
        # Verificar si está actualmente en el servidor
        if invited_user:
            # Verificar posibles alts (cuenta muy nueva)
            account_age = (join_time - datetime.fromisoformat(invite_data.get('account_created', join_time.isoformat()))).days
            if account_age < 7:  # Cuenta creada hace menos de 7 días
                alt_invites.append({
                    'user_id': invited_user_id,
                    'username': invite_data['username'],
                    'account_age': account_age
                })
                continue
            
            # Verificar patrones j4j (mismo usuario invitando mutuamente en corto tiempo)
            mutual_invites = 0
            if str(invited_user_id) in invites_data['user_invites']:
                mutual_invites = len([uid for uid in invites_data['user_invites'][str(invited_user_id)] 
                                    if uid == user_id_str])
            
            if mutual_invites > 0:
                j4j_invites.append({
                    'user_id': invited_user_id,
                    'username': invite_data['username'],
                    'mutual_invites': mutual_invites
                })
                continue
            
            # Invitación válida
            valid_invites.append({
                'user_id': invited_user_id,
                'username': invite_data['username'],
                'joined_at': invite_data['joined_at']
            })
    
    return {
        'total': total_invites,
        'valid': valid_invites,
        'fake': fake_invites,
        'left': left_invites,
        'j4j': j4j_invites,
        'alt': alt_invites
    }

# *** Tarea para limpiar keys expiradas periódicamente ***
@tasks.loop(hours=1)
async def clean_keys_task():
    """Limpia keys expiradas cada hora."""
    clean_expired_keys()

# *** VIEWS MEJORADAS PARA BORRAR TICKETS ***
class ConfirmDeleteView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=60)
        self.user = user
    
    @discord.ui.button(label='✅ Sí, Eliminar', style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message('❌ Esta confirmación no es para ti.', ephemeral=True)
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            channel_name = interaction.channel.name
            await interaction.followup.send('🗑️ Eliminando ticket...', ephemeral=True)
            await interaction.channel.delete(reason=f'Ticket eliminado por {interaction.user.name}')
            print(f"🗑️ Ticket eliminado: {channel_name} por {interaction.user.name}")
        except Exception as e:
            await interaction.followup.send(f'❌ Error al eliminar el ticket: {e}', ephemeral=True)
    
    @discord.ui.button(label='❌ Cancelar', style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message('❌ Esta confirmación no es para ti.', ephemeral=True)
            return
        await interaction.response.send_message('✅ Eliminación cancelada.', ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🗑️ Borrar Ticket', style=discord.ButtonStyle.danger, custom_id='delete_ticket')
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Verificar permisos de administrador
            if interaction.user.guild_permissions.administrator:
                user_has_permission = True
            else:
                # Verificar si es el dueño del ticket buscando su mención en el embed
                user_has_permission = False
                if interaction.message and interaction.message.embeds:
                    embed = interaction.message.embeds[0]
                    if hasattr(embed, 'description') and embed.description:
                        if str(interaction.user.mention) in embed.description:
                            user_has_permission = True
            
            if not user_has_permission:
                await interaction.response.send_message(
                    '❌ Solo los administradores o el dueño del ticket pueden borrarlo.',
                    ephemeral=True
                )
                return
            
            # Crear vista de confirmación
            confirm_view = ConfirmDeleteView(interaction.user)
            confirm_embed = discord.Embed(
                title='⚠️ Confirmar Eliminación',
                description='¿Estás seguro de que quieres eliminar este ticket? Esta acción no se puede deshacer.',
                color=discord.Color.orange()
            )
            
            await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)
            
        except Exception as e:
            print(f"Error en delete_ticket: {e}")
            await interaction.response.send_message('❌ Error al procesar la solicitud.', ephemeral=True)

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
    print(f'🔐 Sistema de verificación: {"✅" if VERIFICATION_CHANNEL_ID else "❌"}')
    
    load_accounts()
    load_keys()
    
    # *** Registrar las Views persistentes ***
    bot.add_view(TicketView())
    bot.add_view(KeyRequestView(0, "", ""))  # View base para solicitudes
    
    try:
        print("🔄 Iniciando sincronización de comandos...")
        
        # OBTENER COMANDOS ANTES DE SINCRONIZAR PARA DIAGNÓSTICO
        commands_before = bot.tree.get_commands()
        print(f"📝 Comandos en el árbol ANTES de sincronizar: {len(commands_before)}")
        
        for cmd in commands_before:
            print(f"   - /{cmd.name}: {cmd.description}")
        
        # SINCRONIZAR COMANDOS (sin limpiar primero)
        synced = await bot.tree.sync()
        print(f"✅ Sincronizados {len(synced)} comandos globales")
        
        # VERIFICAR COMANDOS DESPUÉS DE SINCRONIZAR
        commands_after = bot.tree.get_commands()
        print(f"📝 Comandos en el árbol DESPUÉS de sincronizar: {len(commands_after)}")
        
        if commands_after:
            for cmd in commands_after:
                print(f"   - /{cmd.name}: {cmd.description}")
        else:
            print("❌ ¡CRÍTICO! No hay comandos registrados después de la sincronización")
            print("💡 Solución: Reiniciar el bot completamente")
            
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")
        import traceback
        traceback.print_exc()
    
    distribute_account.start()
    clean_keys_task.start()
    
    # Cargar datos de invitaciones al iniciar
    invites_data = load_invites_data()
    print(f"🔹 Sistema de invitaciones cargado: {len(invites_data['user_invites'])} usuarios con invitaciones registradas")

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

    # EMBED BILINGÜE PARA DISTRIBUCIÓN DE CUENTAS
    embed = discord.Embed(
        title=f"✨ Cuenta Disponible | Available Account ✨",
        color=discord.Color.dark_green()
    )
    
    # Sección en Español
    embed.add_field(
        name="🇪🇸 Español",
        value=(
            f"**¡Se ha liberado una cuenta!**\n"
            f"**Correo:** `{account_to_distribute['gmail']}`\n"
            f"**Contraseña:** `{account_to_distribute['password']}`\n\n"
            "**Reacciona para indicar su estado:**\n"
            "✅ **Usada** - La cuenta funciona correctamente\n"
            "❌ **Error Credenciales** - Contraseña incorrecta\n"
            "🚨 **Cuenta No Sirve/Bloqueada** - Problemas con la cuenta"
        ),
        inline=False
    )
    
    # Sección en Inglés
    embed.add_field(
        name="🇺🇸 English",
        value=(
            f"**An account has been released!**\n"
            f"**Email:** `{account_to_distribute['gmail']}`\n"
            f"**Password:** `{account_to_distribute['password']}`\n\n"
            "**React to indicate its status:**\n"
            "✅ **Used** - Account works correctly\n"
            "❌ **Credential Error** - Wrong password\n"
            "🚨 **Account Not Working/Banned** - Account issues"
        ),
        inline=False
    )
    
    embed.set_footer(text=f"HMFB X | {len(accounts_data['available'])} cuentas restantes | {len(accounts_data['available'])} accounts remaining")

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
    """Maneja las reacciones a los mensajes de distribución - EVITA ACUMULACIÓN."""
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
            # VERIFICAR SI EL USUARIO YA REACCIONÓ Y ELIMINAR REACCIONES ANTERIORES
            if user_id in account['reactions']['users']:
                # El usuario ya reaccionó, eliminar todas sus reacciones anteriores
                try:
                    # Obtener todas las reacciones del mensaje
                    message = await reaction.message.channel.fetch_message(message_id)
                    for r in message.reactions:
                        async for reactor in r.users():
                            if reactor.id == user_id and str(r.emoji) != reacted_emoji:
                                # Eliminar reacciones anteriores del mismo usuario
                                await message.remove_reaction(r.emoji, user)
                except Exception as e:
                    print(f"Error eliminando reacciones anteriores: {e}")
                
                # Actualizar el conteo - restar reacciones anteriores
                for emoji in valid_emojis:
                    if emoji in account['reactions'] and user_id in account['reactions']['users']:
                        account['reactions'][emoji] = max(0, account['reactions'][emoji] - 1)
                
                # Agregar la nueva reacción
                account['reactions'][reacted_emoji] += 1
            else:
                # Usuario reacciona por primera vez
                account['reactions']['users'].append(user_id)
                account['reactions'][reacted_emoji] += 1
            
            save_accounts()
            return

@bot.event
async def on_raw_reaction_remove(payload):
    """Maneja cuando se remueven reacciones para mantener consistencia."""
    if payload.user_id == bot.user.id:
        return
    
    # Verificar si es una reacción de distribución
    if payload.channel_id == CHANNEL_ID and str(payload.emoji) in ["✅","❌", "🚨"]:
        message_id = payload.message_id
        removed_emoji = str(payload.emoji)
        user_id = payload.user_id

        for account in accounts_data['distributed']:
            if account.get('message_id') == message_id:
                if user_id in account['reactions']['users']:
                    account['reactions'][removed_emoji] = max(0, account['reactions'][removed_emoji] - 1)
                    # No removemos al usuario de la lista para evitar que reaccione múltiples veces
                    save_accounts()
                    return

# NUEVO EVENTO: Manejo de reacciones para verificación
@bot.event
async def on_raw_reaction_add(payload):
    """Maneja las reacciones para el sistema de verificación"""
    if payload.user_id == bot.user.id:
        return
    
    # Verificar si es la reacción de verificación
    if (payload.channel_id == VERIFICATION_CHANNEL_ID and 
        str(payload.emoji) == VERIFICATION_EMOJI):
        
        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        role = guild.get_role(VERIFICATION_ROLE_ID)
        
        if not member or not role:
            return
        
        try:
            # Verificar si ya tiene el rol
            if role in member.roles:
                return
                
            # Asignar el rol de verificación
            await member.add_roles(role)
            print(f"✅ Usuario verificado: {member.display_name}")
            
            # ENVIAR MENSAJE DE BIENVENIDA BILINGÜE POR DM
            try:
                welcome_embed = discord.Embed(
                    title="🎉 ¡Verificación Completada! | Verification Completed!",
                    color=discord.Color.green()
                )
                
                # Sección en Español
                welcome_embed.add_field(
                    name="🇪🇸 Español",
                    value=(
                        f"**¡Te has verificado correctamente en {guild.name}!**\n\n"
                        "✅ **¡Bienvenido/a!** Ahora tienes acceso a todos los canales del servidor.\n"
                        "🔓 **Acceso completo** a todas las áreas de la comunidad.\n"
                        "👥 **Puedes interactuar** con other members freely.\n\n"
                        "¡Disfruta de tu estancia en nuestra comunidad!"
                    ),
                    inline=False
                )
                
                # Sección en Inglés
                welcome_embed.add_field(
                    name="🇺🇸 English",
                    value=(
                        f"**You have been successfully verified in {guild.name}!**\n\n"
                        "✅ **Welcome!** You now have access to all server channels.\n"
                        "🔓 **Full access** to all community areas.\n"
                        "👥 **You can interact** with other members freely.\n\n"
                        "Enjoy your stay in our community!"
                    ),
                    inline=False
                )
                
                welcome_embed.set_footer(text="HMFB X | Sistema de Verificación | Verification System")
                
                await member.send(embed=welcome_embed)
                print(f"📩 Mensaje de bienvenida enviado a: {member.display_name}")
                
            except discord.Forbidden:
                print(f"⚠️ No se pudo enviar DM a {member.display_name} (DMs cerrados)")
            except Exception as e:
                print(f"⚠️ Error al enviar DM de bienvenida: {e}")
                
        except Exception as e:
            print(f"❌ Error en verificación automática: {e}")

# NUEVO EVENTO: Tracking de invitaciones
@bot.event
async def on_member_join(member):
    """Registra cuando un usuario se une al servidor"""
    try:
        invites_data = load_invites_data()
        
        # Obtener todas las invitaciones del servidor
        invites = await member.guild.invites()
        
        # Buscar qué invitación fue usada
        for invite in invites:
            if invite.uses > invites_data['invites'].get(str(invite.id), {}).get('uses', 0):
                # Esta es la invitación usada
                inviter_id = str(invite.inviter.id) if invite.inviter else 'unknown'
                invited_id = str(member.id)
                
                # Registrar en user_invites
                if inviter_id not in invites_data['user_invites']:
                    invites_data['user_invites'][inviter_id] = {}
                
                invites_data['user_invites'][inviter_id][invited_id] = {
                    'username': member.name,
                    'joined_at': datetime.now().isoformat(),
                    'invite_code': invite.code,
                    'account_created': member.created_at.isoformat()
                }
                
                # Registrar en join_events
                invites_data['join_events'][invited_id] = {
                    'inviter_id': inviter_id,
                    'invite_code': invite.code,
                    'joined_at': datetime.now().isoformat()
                }
                
                # Actualizar contador de uses
                if str(invite.id) not in invites_data['invites']:
                    invites_data['invites'][str(invite.id)] = {}
                
                invites_data['invites'][str(invite.id)]['uses'] = invite.uses
                invites_data['invites'][str(invite.id)]['inviter_id'] = inviter_id
                invites_data['invites'][str(invite.id)]['code'] = invite.code
                
                save_invites_data(invites_data)
                print(f"📥 Usuario {member.name} se unió mediante invitación de {invite.inviter.name if invite.inviter else 'unknown'}")
                break
        
    except Exception as e:
        print(f"❌ Error en on_member_join: {e}")

@bot.event
async def on_member_remove(member):
    """Registra cuando un usuario abandona el servidor"""
    try:
        invites_data = load_invites_data()
        user_id = str(member.id)
        
        # Marcar como left en todas las invitaciones donde aparezca
        for inviter_id, user_invites in invites_data['user_invites'].items():
            if user_id in user_invites:
                invites_data['user_invites'][inviter_id][user_id]['left_at'] = datetime.now().isoformat()
        
        save_invites_data(invites_data)
        print(f"📤 Usuario {member.name} abandonó el servidor")
        
    except Exception as e:
        print(f"❌ Error en on_member_remove: {e}")

# --- COMANDOS DE BARRA ---

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
        
        # EMBED BILINGÜE PARA KEY GENERADA
        embed = discord.Embed(
            title='🔑 Nueva Key Generada | New Key Generated',
            color=discord.Color.green()
        )
        embed.add_field(name='🔑 Key', value=f'`{new_key}`', inline=False)
        embed.add_field(name='👤 Creada por | Created by', value=interaction.user.mention, inline=True)
        
        if expires_at:
            embed.add_field(name='⏰ Expira | Expires', value=f'<t:{int(expires_at.timestamp())}:R>', inline=True)
            embed.add_field(name='⏱️ Duración | Duration', value=readable_time, inline=True)
            embed.add_field(name='📊 Estado | Status', value='🟢 ACTIVA (Temporal) | ACTIVE (Temporary)', inline=False)
        else:
            embed.add_field(name='⏰ Expira | Expires', value='Nunca | Never', inline=True)
            embed.add_field(name='📊 Estado | Status', value='🟢 ACTIVA (Permanente) | ACTIVE (Permanent)', inline=False)
        
        examples = (
            "**Ejemplos | Examples:**\n"
            "• `/key 6h` - 6 horas | 6 hours\n"
            "• `/key 2d12h` - 2 días y 12 horas | 2 days and 12 hours\n"
            "• `/key 30m` - 30 minutos | 30 minutes\n"
            "• `/key permanent` - Permanente | Permanent"
        )
        embed.add_field(name='💡 Formatos válidos | Valid formats', value=examples, inline=False)
        embed.set_footer(text="HMFB X")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except ValueError as e:
        error_embed = discord.Embed(
            title="❌ Formato de tiempo inválido | Invalid time format",
            color=discord.Color.red()
        )
        error_embed.add_field(
            name="💡 Formatos válidos | Valid formats",
            value=(
                "Usa: `6s`, `6m`, `6h`, `6d`, `1h30m`, `2d12h` o `permanent`\n"
                "**Ejemplos | Examples:**\n"
                "• `/key 6h` - 6 horas | 6 hours\n"
                "• `/key 2d12h` - 2 días y 12 horas | 2 days and 12 hours\n"
                "• `/key 30m` - 30 minutos | 30 minutes\n"
                "• `/key permanent` - Permanente | Permanent"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=error_embed, ephemeral=True)

@bot.tree.command(name="access", description="Validar tu key de acceso")
async def access_command(interaction: discord.Interaction, key: str):
    """Validar una key de acceso"""
    key_upper = key.upper()
    
    if key_upper in keys_data['keys']:
        key_info = keys_data['keys'][key_upper]
        
        if key_info.get('expires_at'):
            expires_at = datetime.fromisoformat(key_info['expires_at'])
            if datetime.now() > expires_at:
                await interaction.response.send_message('❌ Esta key ha expirado. | This key has expired.', ephemeral=True)
                return
        
        if key_info['used']:
            await interaction.response.send_message('❌ Esta key ya ha sido utilizada. | This key has already been used.', ephemeral=True)
        else:
            key_info['used'] = True
            key_info['user_id'] = interaction.user.id
            key_info['used_at'] = datetime.now().isoformat()
            
            if interaction.user.id not in keys_data['users_with_access']:
                keys_data['users_with_access'].append(interaction.user.id)
            
            save_keys()
            
            embed = discord.Embed(
                title='✅ Acceso Concedido | Access Granted',
                description='Ahora tienes acceso al comando `/cuenta` | You now have access to the `/cuenta` command',
                color=discord.Color.green()
            )
            
            if key_info.get('expires_at'):
                expires_at = datetime.fromisoformat(key_info['expires_at'])
                embed.add_field(name='⏰ Key expira | Key expires', value=f'<t:{int(expires_at.timestamp())}:R>')
            
            embed.set_footer(text="HMFB X")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message('❌ Key inválida. | Invalid key.', ephemeral=True)

@bot.tree.command(name="cuenta", description="Obtener una cuenta (Requiere key)")
async def cuenta_command(interaction: discord.Interaction):
    """Obtener una cuenta del inventario"""
    if not has_access(interaction.user.id):
        embed = discord.Embed(
            title="❌ Acceso Denegado | Access Denied",
            description=(
                "No tienes acceso a este comando. | You don't have access to this command.\n"
                "Usa `/get-key` para solicitar acceso. | Use `/get-key` to request access."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if not accounts_data['available']:
        embed = discord.Embed(
            title="❌ Sin Stock | Out of Stock",
            description=(
                "No hay cuentas disponibles en este momento. | No accounts available at the moment.\n"
                "Vuelve a intentarlo más tarde. | Please try again later."
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    account = accounts_data['available'].pop(0)
    save_accounts()
    
    try:
        # EMBED BILINGÜE PARA CUENTA OBTENIDA
        embed = discord.Embed(
            title='📧 Cuenta Obtenida | Account Obtained',
            description='Aquí tienes tu cuenta: | Here is your account:',
            color=discord.Color.blue()
        )
        embed.add_field(name='📧 Correo | Email', value=f'`{account["gmail"]}`', inline=False)
        embed.add_field(name='🔒 Contraseña | Password', value=f'`{account["password"]}`', inline=False)
        embed.set_footer(text='HMFB X | dsc.gg/hmfb')
        
        await interaction.user.send(embed=embed)
        
        success_embed = discord.Embed(
            title="✅ Cuenta Enviada | Account Sent",
            description="Tu cuenta ha sido enviada por mensaje privado. | Your account has been sent via private message.",
            color=discord.Color.green()
        )
        success_embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=success_embed, ephemeral=True)
        
        update_log(account, "CLAIMED")
        
    except discord.Forbidden:
        error_embed = discord.Embed(
            title="❌ Error de DM | DM Error",
            description=(
                "No puedo enviarte mensajes privados. | I can't send you private messages.\n"
                "Activa tus DMs y vuelve a intentarlo. | Enable your DMs and try again."
            ),
            color=discord.Color.red()
        )
        error_embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=error_embed, ephemeral=True)
        accounts_data['available'].insert(0, account)
        save_accounts()

# NUEVO COMANDO: Sistema de verificación BILINGÜE
@bot.tree.command(name="verify", description="Configura el sistema de verificación (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def verify_setup(interaction: discord.Interaction):
    """Crea el embed de verificación con reacción - VERSIÓN BILINGÜE"""
    if not VERIFICATION_CHANNEL_ID or not VERIFICATION_ROLE_ID:
        embed = discord.Embed(
            title="❌ Error de Configuración | Configuration Error",
            description=(
                "El sistema de verificación no está configurado correctamente. | The verification system is not properly configured.\n"
                "Verifica las variables de entorno VERIFICATION_CHANNEL_ID y VERIFICATION_ROLE_ID. | Check VERIFICATION_CHANNEL_ID and VERIFICATION_ROLE_ID environment variables."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    verification_channel = bot.get_channel(VERIFICATION_CHANNEL_ID)
    if not verification_channel:
        embed = discord.Embed(
            title="❌ Canal No Encontrado | Channel Not Found",
            description="No se pudo encontrar el canal de verificación. | Could not find the verification channel.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    try:
        # EMBED DE VERIFICACIÓN BILINGÜE
        embed = discord.Embed(
            title="🔐 Verificación de Usuario | User Verification",
            color=discord.Color.blue()
        )
        
        # Sección en Español
        embed.add_field(
            name="🇪🇸 Español",
            value=(
                "**¡Bienvenido/a al servidor!**\n\n"
                f"Para acceder a todos los canales del servidor, debes verificarte.\n"
                f"Simplemente reacciona con {VERIFICATION_EMOJI} a este mensaje y "
                f"se te asignará el rol de miembro verificado automáticamente.\n\n"
                "**¿Problemas?** Contacta a un administrador."
            ),
            inline=False
        )
        
        # Sección en Inglés
        embed.add_field(
            name="🇺🇸 English",
            value=(
                "**Welcome to the server!**\n\n"
                f"To access all server channels, you must verify yourself.\n"
                f"Simply react with {VERIFICATION_EMOJI} to this message and "
                f"the verified member role will be automatically assigned to you.\n\n"
                "**Having issues?** Contact an administrator."
            ),
            inline=False
        )
        
        if VERIFICATION_IMAGE_URL:
            embed.set_image(url=VERIFICATION_IMAGE_URL)
        
        embed.set_footer(text="HMFB X")
        
        message = await verification_channel.send(embed=embed)
        await message.add_reaction(VERIFICATION_EMOJI)
        
        success_embed = discord.Embed(
            title="✅ Sistema Configurado | System Configured",
            description=f"Sistema de verificación configurado correctamente en {verification_channel.mention} | Verification system successfully configured in {verification_channel.mention}",
            color=discord.Color.green()
        )
        success_embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=success_embed, ephemeral=True)
        
        print(f"✅ Sistema de verificación BILINGÜE configurado por {interaction.user.name}")
        
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Error | Error",
            description=f"Error al configurar la verificación: {str(e)} | Error setting up verification: {str(e)}",
            color=discord.Color.red()
        )
        error_embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=error_embed, ephemeral=True)

# NUEVO COMANDO: Sistema de invitaciones
@bot.tree.command(name="invites", description="Analiza las invitaciones de un usuario")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    usuario="Usuario a analizar (deja vacío para analizarte a ti mismo)"
)
async def invites_command(interaction: discord.Interaction, usuario: discord.Member = None):
    """Analiza las invitaciones de un usuario - VERSIÓN BILINGÜE"""
    target_user = usuario or interaction.user
    invites_data = load_invites_data()
    
    analysis = analyze_user_invites(invites_data, target_user.id, interaction.guild)
    
    if not analysis:
        embed = discord.Embed(
            title="📊 Análisis de Invitaciones | Invites Analysis",
            description=(
                f"**{target_user.mention} no tiene invitaciones registradas.**\n"
                f"**{target_user.mention} has no registered invites.**"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="HMFB X")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Calcular porcentajes
    total = analysis['total']
    valid_count = len(analysis['valid'])
    fake_count = len(analysis['fake'])
    left_count = len(analysis['left'])
    j4j_count = len(analysis['j4j'])
    alt_count = len(analysis['alt'])
    
    legit_count = valid_count
    fraud_count = fake_count + left_count + j4j_count + alt_count
    
    legit_percentage = (legit_count / total * 100) if total > 0 else 0
    fraud_percentage = (fraud_count / total * 100) if total > 0 else 0
    
    # Crear embed de análisis BILINGÜE
    embed = discord.Embed(
        title=f"📊 Análisis de Invitaciones | Invites Analysis - {target_user.display_name}",
        color=discord.Color.blue()
    )
    
    # Estadísticas generales
    embed.add_field(
        name="📈 Estadísticas Generales | General Statistics",
        value=(
            f"**Total de Invitaciones | Total Invites:** {total}\n"
            f"**Legítimas | Legitimate:** {legit_count} ({legit_percentage:.1f}%)\n"
            f"**Fraudulentas | Fraudulent:** {fraud_count} ({fraud_percentage:.1f}%)"
        ),
        inline=False
    )
    
    # Desglose por categorías
    breakdown_text = (
        f"✅ **Válidas | Valid:** {valid_count}\n"
        f"❌ **Fake (<5min):** {fake_count}\n"
        f"🚪 **Lefts | Abandonaron:** {left_count}\n"
        f"🔄 **J4J | Join-for-Join:** {j4j_count}\n"
        f"👥 **Alts | Cuentas Alternas:** {alt_count}"
    )
    
    embed.add_field(
        name="🔍 Desglose por Categoría | Category Breakdown",
        value=breakdown_text,
        inline=False
    )
    
    # Evaluación de calidad
    quality_emoji = "🟢" if legit_percentage >= 70 else "🟡" if legit_percentage >= 40 else "🔴"
    quality_text = "Excelente | Excellent" if legit_percentage >= 70 else "Regular | Average" if legit_percentage >= 40 else "Pobre | Poor"
    
    embed.add_field(
        name="🏆 Evaluación de Calidad | Quality Assessment",
        value=f"{quality_emoji} **{quality_text}** - {legit_percentage:.1f}% legítimas | legitimate",
        inline=False
    )
    
    # Información adicional si hay problemas
    if fraud_count > legit_count:
        advice = (
            "⚠️ **Alerta | Alert:** Más del 50% de las invitaciones son sospechosas.\n"
            "**Recomendación | Recommendation:** Revisar este usuario para posible spam."
        )
        embed.add_field(name="🚨 Recomendación | Recommendation", value=advice, inline=False)
    
    embed.set_footer(text=f"HMFB X | Análisis generado | Analysis generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# NUEVO COMANDO: Resetear invitaciones
@bot.tree.command(name="reset-invites", description="Resetea todas las estadísticas de invitaciones (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_invites_command(interaction: discord.Interaction):
    """Resetea todas las estadísticas de invitaciones a cero - VERSIÓN BILINGÜE"""
    
    # Crear embed de confirmación
    confirm_embed = discord.Embed(
        title="⚠️ Confirmar Reset de Invitaciones | Confirm Invites Reset",
        description=(
            "**¿Estás seguro de que quieres resetear TODAS las estadísticas de invitaciones?**\n"
            "**Are you sure you want to reset ALL invite statistics?**\n\n"
            "🗑️ **Esto eliminará:** | **This will delete:**\n"
            "• Todas las invitaciones registradas | All registered invites\n"
            "• Historial de joins/leaves | Join/leave history\n"
            "• Estadísticas de todos los usuarios | All users' statistics\n\n"
            "**Esta acción NO se puede deshacer.** | **This action CANNOT be undone.**"
        ),
        color=discord.Color.orange()
    )
    confirm_embed.set_footer(text="HMFB X")
    
    # Crear vista de confirmación
    class ResetConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label='✅ Sí, Resetear Todo', style=discord.ButtonStyle.danger)
        async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message('❌ Solo los administradores pueden usar este botón.', ephemeral=True)
                return
            
            # Resetear todos los datos de invitaciones
            reset_data = {'invites': {}, 'join_events': {}, 'user_invites': {}}
            save_invites_data(reset_data)
            
            success_embed = discord.Embed(
                title="✅ Invitaciones Reseteadas | Invites Reset",
                description=(
                    "**Todas las estadísticas de invitaciones han sido reseteadas correctamente.**\n"
                    "**All invite statistics have been successfully reset.**\n\n"
                    "📊 **Nuevo estado | New status:**\n"
                    "• Invitaciones registradas: 0 | Registered invites: 0\n"
                    "• Usuarios con invitaciones: 0 | Users with invites: 0\n"
                    "• Eventos de join: 0 | Join events: 0"
                ),
                color=discord.Color.green()
            )
            success_embed.set_footer(text="HMFB X")
            
            # Deshabilitar botones
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
            print(f"🔄 Invitaciones reseteadas por {interaction.user.name}")
        
        @discord.ui.button(label='❌ Cancelar', style=discord.ButtonStyle.secondary)
        async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message('❌ Solo los administradores pueden usar este botón.', ephemeral=True)
                return
            
            cancel_embed = discord.Embed(
                title="✅ Reset Cancelado | Reset Cancelled",
                description="El reset de invitaciones ha sido cancelado. | The invites reset has been cancelled.",
                color=discord.Color.blue()
            )
            cancel_embed.set_footer(text="HMFB X")
            
            # Deshabilitar botones
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            
            await interaction.response.send_message(embed=cancel_embed, ephemeral=True)
    
    await interaction.response.send_message(embed=confirm_embed, view=ResetConfirmView(), ephemeral=True)

# --- Comandos de Prefijo ---

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    email_lower = email.lower()

    if email_lower in registered_emails:
        embed = discord.Embed(
            title="❌ Cuenta Existente | Existing Account",
            description=f"La cuenta con correo **{email}** ya existe en el inventario. | The account with email **{email}** already exists in the inventory.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)
        return

    await ctx.send("✅ Recibida la información. | Information received.")

    new_account = {'username':email,'gmail':email,'password':password}
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower)
    save_accounts()
    update_log(new_account,"ADDED")

    embed = discord.Embed(
        title="✅ Cuenta Añadida | Account Added",
        description="La cuenta ha sido añadida al inventario y está lista para ser distribuida. | The account has been added to the inventory and is ready for distribution.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📧 Correo (Microsoft) | Email (Microsoft)", value=email)
    embed.add_field(name="🔒 Contraseña | Password", value=password)
    embed.add_field(name="📊 Inventario Total | Total Inventory", value=f"{len(accounts_data['available'])} disponibles | {len(accounts_data['available'])} available")
    embed.set_footer(text="HMFB X")
    await ctx.send(embed=embed)

@bot.command(name='importaccounts', help='Importa varias cuentas desde archivo import_accounts.txt con formato: correo:contraseña')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        embed = discord.Embed(
            title="❌ Archivo No Encontrado | File Not Found",
            description=f"No se encontró el archivo {file_path}. Asegúrate de crearlo con formato `correo:contraseña` por línea. | File {file_path} not found. Make sure to create it with `email:password` format per line.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="⏳ Importando Cuentas | Importing Accounts",
        description="El proceso de importación ha comenzado... | The import process has started...",
        color=discord.Color.orange()
    )
    embed.set_footer(text="HMFB X")
    await ctx.send(embed=embed)
    
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
        await ctx.send(f"⚠️ **{fail_count}** líneas con formato incorrecto. Quedan en `{file_path}` para corrección. | **{fail_count}** lines with incorrect format. Remain in `{file_path}` for correction.")
    else:
        remove_import_file(file_path)
    
    # EMBED BILINGÜE DE RESULTADOS
    embed = discord.Embed(
        title="📊 Resultados de Importación | Import Results",
        color=discord.Color.green()
    )
    embed.add_field(
        name="✅ Éxitos | Successes",
        value=f"**{success_count}** cuentas importadas correctamente | **{success_count}** accounts successfully imported",
        inline=False
    )
    embed.add_field(
        name="🔄 Duplicados | Duplicates",
        value=f"**{duplicate_count}** cuentas ya en inventario (omitidas) | **{duplicate_count}** accounts already in inventory (skipped)",
        inline=True
    )
    embed.add_field(
        name="❌ Fallos | Failures",
        value=f"**{fail_count}** líneas con formato incorrecto | **{fail_count}** lines with incorrect format",
        inline=True
    )
    embed.set_footer(text="HMFB X")
    await ctx.send(embed=embed)

@add_account.error
async def add_account_error(ctx,error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Uso Incorrecto | Incorrect Usage",
            description="Uso incorrecto: `!addaccount <correo_completo> <contraseña>` | Incorrect usage: `!addaccount <complete_email> <password>`",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permiso Denegado | Permission Denied",
            description="Permiso denegado. Solo administradores pueden usar este comando. | Permission denied. Only administrators can use this command.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)
    else:
        print(f"Error inesperado en add_account: {error}")
        embed = discord.Embed(
            title="❌ Error | Error",
            description="Error al añadir la cuenta. Revisa la consola para más detalles. | Error adding account. Check console for details.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)

# --- Comando Sync Mejorado ---
@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """Comando mejorado para sincronizar comandos"""
    try:
        # Mensaje de inicio
        embed_loading = discord.Embed(
            title="🔄 Sincronizando Comandos...",
            description="Esto puede tomar hasta 1 hora en propagarse globalmente",
            color=discord.Color.orange()
        )
        loading_msg = await ctx.send(embed=embed_loading)
        
        # DIAGNÓSTICO ANTES
        commands_before = bot.tree.get_commands()
        
        # SINCRONIZAR
        synced = await bot.tree.sync()
        
        # DIAGNÓSTICO DESPUÉS
        commands_after = bot.tree.get_commands()
        
        # EMBED DE RESULTADO
        embed = discord.Embed(
            title="✅ Comandos Sincronizados | Commands Synced",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="📊 Estadísticas | Statistics",
            value=(
                f"**Comandos sincronizados:** {len(synced)}\n"
                f"**Comandos en árbol:** {len(commands_after)}\n"
                f"**Tiempo de propagación:** 1-60 minutos"
            ),
            inline=False
        )
        
        # LISTA DE COMANDOS
        if commands_after:
            command_list = "\n".join([f"• `/{cmd.name}` - {cmd.description}" for cmd in commands_after])
            embed.add_field(
                name="📝 Comandos Disponibles | Available Commands",
                value=command_list,
                inline=False
            )
        else:
            embed.add_field(
                name="❌ Advertencia | Warning",
                value="No se detectaron comandos. Esto es normal - pueden tardar en aparecer.",
                inline=False
            )
        
        embed.add_field(
            name="💡 Nota Importante | Important Note",
            value=(
                "Los comandos pueden tardar **hasta 1 hora** en aparecer para todos los usuarios.\n"
                "Si no ves los comandos, espera o reinvita al bot con el scope `applications.commands`"
            ),
            inline=False
        )
        
        embed.set_footer(text="HMFB X")
        
        await loading_msg.edit(embed=embed)
        
        # LOG EN CONSOLA
        print(f"🔧 Sincronización manual ejecutada por {ctx.author.name}")
        print(f"📊 Comandos sincronizados: {len(synced)}")
        print("📝 Lista de comandos:")
        for cmd in commands_after:
            print(f"   - /{cmd.name}")
            
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error de Sincronización | Sync Error",
            description=f"**Error:** {str(e)}\n\nLos comandos pueden aparecer automáticamente en unos minutos.",
            color=discord.Color.red()
        )
        embed.set_footer(text="HMFB X")
        await ctx.send(embed=embed)
        print(f"❌ Error en sync: {e}")

# --- Comando de Emergencia ---
@bot.command(name='force-cmds')
@commands.has_permissions(administrator=True)
async def force_commands(ctx):
    """Comando de emergencia para forzar comandos"""
    try:
        # Sincronizar con servidor específico
        guild_synced = await bot.tree.sync(guild=ctx.guild)
        
        embed = discord.Embed(
            title="⚡ Comandos Forzados",
            description=f"Sincronizados {len(guild_synced)} comandos en este servidor",
            color=discord.Color.blue()
        )
        
        # Listar comandos forzados
        commands_list = bot.tree.get_commands(guild=ctx.guild)
        if commands_list:
            cmd_names = [f"`/{cmd.name}`" for cmd in commands_list]
            embed.add_field(
                name="📝 Comandos en este servidor",
                value=", ".join(cmd_names),
                inline=False
            )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

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
