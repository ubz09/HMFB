# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask
import random
import string

# --- Configuración Inicial ---
TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
DISTRIBUTION_INTERVAL_MINUTES = 10.0

# *** CORREGIDO: Configuración separada para canal de solicitudes ***
try:
    REQUEST_CHANNEL_ID = int(os.environ['REQUEST_CHANNEL_ID'])
except (KeyError, ValueError):
    # Si no existe o es inválido, usar un valor por defecto y mostrar advertencia
    REQUEST_CHANNEL_ID = CHANNEL_ID
    print("⚠️  REQUEST_CHANNEL_ID no configurado o inválido, usando CHANNEL_ID por defecto")

# --- Rutas de Archivos ---
DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')
# *** NUEVO: Archivo para almacenar keys y usuarios con acceso ***
KEYS_FILE = os.path.join(DATA_DIR, 'keys.json')

# Asegurarse de que las carpetas y archivos existan
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

for file_path in [ACCOUNTS_FILE, LOGS_FILE, KEYS_FILE]:
    if not os.path.exists(file_path):
        if file_path.endswith('.json'):
            # Inicializar el archivo JSON con las estructuras necesarias
            if file_path == KEYS_FILE:
                # Estructura para keys: {key: {used: bool, user_id: int, created_by: int}, users_with_access: [user_ids]}
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'keys': {}, 'users_with_access': []}, f, indent=4)
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({'available': [], 'distributed': []}, f, indent=4)
        else:
            # Inicializar el archivo de logs
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
# *** NUEVO: Conjunto para una búsqueda rápida de emails ya registrados ***
registered_emails = set()
# *** NUEVO: Datos de keys y acceso ***
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
                # Reconstruir el conjunto de emails registrados
                registered_emails.clear()
                # Las cuentas ya distribuidas son las que actúan como "logs"
                for account in accounts_data['distributed']:
                    if 'gmail' in account:
                        registered_emails.add(account['gmail'].lower())
                # También registramos las cuentas que aún están en 'available'
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
    # Usamos el 'gmail' (ahora cualquier email) como identificador principal en el log
    log_entry = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"STATUS: {status} | Email: {account_info['gmail']} | Pass: {account_info['password']}\n"
    )
    try:
        with open(LOGS_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Error escribiendo log: {e}")

# *** NUEVO: Función para eliminar el archivo de importación ***
def remove_import_file(file_path):
    """Elimina el archivo de importación de cuentas."""
    try:
        os.remove(file_path)
        print(f"Archivo de importación eliminado: {file_path}")
    except Exception as e:
        print(f"Error al eliminar archivo {file_path}: {e}")

# *** NUEVO: Función para generar keys ***
def generate_key():
    """Genera una key en formato HMFB-XXXX-XXXX-XXXX"""
    parts = []
    # Primera parte fija "HMFB"
    parts.append("HMFB")
    # Tres partes de 4 caracteres aleatorios (números)
    for _ in range(3):
        part = ''.join(random.choices(string.digits, k=4))
        parts.append(part)
    return '-'.join(parts)

# *** NUEVO: Función para verificar si usuario tiene acceso ***
def has_access(user_id):
    """Verifica si un usuario tiene acceso al comando /cuenta"""
    return user_id in keys_data['users_with_access']

# *** NUEVO: Clase Modal para /get-key ***
class KeyRequestModal(discord.ui.Modal, title='Solicitud de Key'):
    def __init__(self):
        super().__init__()
    
    name = discord.ui.TextInput(
        label='Nombre',
        placeholder='Ingresa tu nombre completo',
        required=True,
        max_length=100
    )
    
    reason = discord.ui.TextInput(
        label='Razón de la solicitud',
        placeholder='Explica por qué necesitas acceso',
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

# *** NUEVO: View para los botones de aceptar/rechazar ***
class KeyRequestView(discord.ui.View):
    def __init__(self, user_id, user_name, user_reason):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.user_name = user_name
        self.user_reason = user_reason
    
    @discord.ui.button(label='Aceptar', style=discord.ButtonStyle.success, custom_id='accept_key')
    async def accept_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Crear ticket con el usuario
        user = interaction.guild.get_member(self.user_id)
        if user:
            try:
                # Crear canal privado
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                
                channel = await interaction.guild.create_text_channel(
                    f'ticket-{user.display_name}',
                    overwrites=overwrites
                )
                
                # Enviar mensaje en el ticket
                embed = discord.Embed(
                    title='🎫 Ticket de Key Aceptado',
                    description=f'Hola {user.mention}, tu solicitud de key ha sido **aceptada**.',
                    color=discord.Color.green()
                )
                embed.add_field(name='Nombre', value=self.user_name, inline=False)
                embed.add_field(name='Razón', value=self.user_reason, inline=False)
                embed.add_field(name='Próximos pasos', value='Un administrador te proporcionará una key pronto.', inline=False)
                
                await channel.send(embed=embed)
                await interaction.response.send_message(f'✅ Ticket creado: {channel.mention}', ephemeral=True)
                
                # Actualizar el embed original
                embed_original = interaction.message.embeds[0]
                embed_original.color = discord.Color.green()
                embed_original.add_field(name='Estado', value='✅ ACEPTADO', inline=False)
                embed_original.add_field(name='Aceptado por', value=interaction.user.mention, inline=False)
                embed_original.add_field(name='Ticket', value=channel.mention, inline=False)
                
                self.accept_key.disabled = True
                self.reject_key.disabled = True
                await interaction.message.edit(embed=embed_original, view=self)
                
            except Exception as e:
                await interaction.response.send_message(f'❌ Error al crear ticket: {e}', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Usuario no encontrado en el servidor', ephemeral=True)
    
    @discord.ui.button(label='Rechazar', style=discord.ButtonStyle.danger, custom_id='reject_key')
    async def reject_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.guild.get_member(self.user_id)
        if user:
            try:
                # Notificar al usuario via DM
                embed = discord.Embed(
                    title='❌ Solicitud de Key Rechazada',
                    description='Tu solicitud de key ha sido rechazada por un administrador.',
                    color=discord.Color.red()
                )
                embed.add_field(name='Nombre', value=self.user_name, inline=False)
                embed.add_field(name='Razón', value=self.user_reason, inline=False)
                embed.add_field(name='Rechazado por', value=interaction.user.mention, inline=False)
                
                await user.send(embed=embed)
                await interaction.response.send_message('✅ Usuario notificado del rechazo', ephemeral=True)
                
            except:
                await interaction.response.send_message('✅ Solicitud rechazada (no se pudo notificar al usuario via DM)', ephemeral=True)
        
        # Actualizar el embed original
        embed_original = interaction.message.embeds[0]
        embed_original.color = discord.Color.red()
        embed_original.add_field(name='Estado', value='❌ RECHAZADO', inline=False)
        embed_original.add_field(name='Rechazado por', value=interaction.user.mention, inline=False)
        
        self.accept_key.disabled = True
        self.reject_key.disabled = True
        await interaction.message.edit(embed=embed_original, view=self)

# --- Tasks y Eventos ---

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f'🤖 Bot conectado como {bot.user}!')
    print(f'📊 Canal de distribución: {CHANNEL_ID}')
    print(f'📨 Canal de solicitudes: {REQUEST_CHANNEL_ID}')
    load_accounts()
    load_keys()
    # Iniciar el bucle de distribución
    distribute_account.start()
    
    # Sincronizar comandos de barra
    try:
        synced = await bot.tree.sync()
        print(f"✅ Sincronizados {len(synced)} comandos de barra")
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")

@tasks.loop(minutes=DISTRIBUTION_INTERVAL_MINUTES)
async def distribute_account():
    """Tarea de bucle para distribuir cuentas en el canal configurado."""
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    if not channel or not accounts_data['available']:
        return

    # Sacar la primera cuenta disponible
    account_to_distribute = accounts_data['available'].pop(0)

    required_keys = ['gmail', 'password']
    # Comprobamos solo el correo y la contraseña
    if not all(key in account_to_distribute for key in required_keys):
        accounts_data['available'].insert(0, account_to_distribute)
        return

    # Crear el Embed para la distribución
    embed = discord.Embed(
        title=f"✨ Cuenta Disponible | Correo: {account_to_distribute['gmail']} ✨",
        description="¡Se ha liberado una cuenta! Reacciona para indicar su estado:",
        color=discord.Color.dark_green()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=f"`{account_to_distribute['gmail']}`", inline=False)
    embed.add_field(name="🔒 Contraseña", value=f"`{account_to_distribute['password']}`", inline=False)
    embed.set_footer(text=f"Reacciona: ✅ Usada | ❌ Error Credenciales | 🚨 Cuenta No Sirve/Bloqueada | {len(accounts_data['available'])} restantes.")

    try:
        # Enviar el mensaje y añadir las tres reacciones
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("🚨")

        # Guardar la información de la distribución (Esto ya actúa como el "log" solicitado)
        account_data_distributed = account_to_distribute.copy()
        account_data_distributed['distribution_date'] = datetime.now().isoformat()
        account_data_distributed['message_id'] = message.id
        account_data_distributed['reactions'] = {'✅':0,'❌':0,'🚨':0,'users':[]}
        accounts_data['distributed'].append(account_data_distributed)
        
        # *** NUEVO: La cuenta ya está en 'distributed', no se requiere un log JSON adicional.
        # Solo se requiere actualizar el log de texto y guardar los datos principales.
        save_accounts()
        update_log(account_to_distribute, "DISTRIBUTED")
        
    except:
        # Si falla el envío (ej. el bot no tiene permisos), devolver la cuenta
        accounts_data['available'].insert(0, account_to_distribute)


@bot.event
async def on_reaction_add(reaction, user):
    """Maneja las reacciones a los mensajes de distribución."""
    if user.bot:
        return

    valid_emojis = ["✅","❌", "🚨"]

    # Comprobar si la reacción está en el canal correcto y es un emoji válido
    if reaction.message.channel.id != CHANNEL_ID or str(reaction.emoji) not in valid_emojis:
        return

    message_id = reaction.message.id
    reacted_emoji = str(reaction.emoji)
    user_id = user.id

    # Buscar la cuenta distribuida correspondiente
    for account in accounts_data['distributed']:
        if account.get('message_id') == message_id:
            # Comprobar si el usuario ya reaccionó
            if user_id in account['reactions']['users']:
                await reaction.remove(user)
                return

            # Registrar la nueva reacción
            account['reactions']['users'].append(user_id)
            account['reactions'][reacted_emoji] += 1
            save_accounts()
            return

# --- Comandos de Barra (NUEVOS) ---

@bot.tree.command(name="get-key", description="Solicitar una key de acceso")
async def get_key(interaction: discord.Interaction):
    """Comando para solicitar una key de acceso"""
    modal = KeyRequestModal()
    await interaction.response.send_modal(modal)
    
    # Esperar a que se complete el modal
    await modal.wait()
    
    # Enviar la solicitud al canal de administradores
    channel = bot.get_channel(REQUEST_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title='🔑 Solicitud de Key',
            description=f'Solicitud de key de {interaction.user.mention}',
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed.add_field(name='👤 Nombre', value=modal.name.value, inline=False)
        embed.add_field(name='📝 Razón', value=modal.reason.value, inline=False)
        embed.add_field(name='🆔 User ID', value=interaction.user.id, inline=False)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        
        view = KeyRequestView(interaction.user.id, modal.name.value, modal.reason.value)
        await channel.send(embed=embed, view=view)
        
        await interaction.followup.send('✅ Tu solicitud ha sido enviada a los administradores.', ephemeral=True)
    else:
        await interaction.followup.send('❌ Error: Canal de solicitudes no configurado.', ephemeral=True)

@bot.tree.command(name="key", description="Generar una nueva key de acceso (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def generate_key_command(interaction: discord.Interaction):
    """Genera una nueva key de acceso"""
    new_key = generate_key()
    keys_data['keys'][new_key] = {
        'used': False,
        'user_id': None,
        'created_by': interaction.user.id,
        'created_at': datetime.now().isoformat()
    }
    save_keys()
    
    embed = discord.Embed(
        title='🔑 Nueva Key Generada',
        description=f'Key: `{new_key}`',
        color=discord.Color.green()
    )
    embed.add_field(name='Creada por', value=interaction.user.mention)
    embed.add_field(name='Estado', value='🟢 DISPONIBLE')
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="access", description="Validar tu key de acceso")
async def access_command(interaction: discord.Interaction, key: str):
    """Validar una key de acceso"""
    key_upper = key.upper()
    
    if key_upper in keys_data['keys']:
        key_info = keys_data['keys'][key_upper]
        
        if key_info['used']:
            await interaction.response.send_message('❌ Esta key ya ha sido utilizada.', ephemeral=True)
        else:
            # Marcar key como usada y dar acceso al usuario
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
    
    # Obtener la primera cuenta disponible
    account = accounts_data['available'].pop(0)
    save_accounts()
    
    # Enviar la cuenta via DM
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
        
        # Registrar en logs
        update_log(account, "CLAIMED")
        
    except discord.Forbidden:
        await interaction.response.send_message(
            '❌ No puedo enviarte mensajes privados. Activa tus DMs y vuelve a intentarlo.',
            ephemeral=True
        )
        # Devolver la cuenta al inventario si no se pudo enviar
        accounts_data['available'].insert(0, account)
        save_accounts()

# --- Comandos de Prefijo (EXISTENTES) ---

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """
    Añade una cuenta al inventario, usando el email como identificador principal.
    """
    email_lower = email.lower()

    # *** NUEVO: Chequeo de duplicados al añadir manualmente ***
    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta con correo **{email}** ya existe en el inventario.")
        return

    await ctx.send("✅ Recibida la información.")

    # El campo 'username' se utiliza internamente para mantener la estructura,
    # pero ahora guarda el email.
    new_account = {'username':email,'gmail':email,'password':password}
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower) # Añadir al set
    save_accounts()
    update_log(new_account,"ADDED")

    # Enviar confirmación con Embed
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
    """
    Importa cuentas desde un archivo de texto con formato email:contraseña, 
    evitando duplicados y eliminando el archivo después de un procesamiento exitoso.
    """
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        await ctx.send(f"❌ No se encontró el archivo {file_path}. Asegúrate de crearlo con formato `correo:contraseña` por línea.")
        return

    await ctx.send("⏳ Importando cuentas...")
    success_count = 0
    fail_count = 0
    duplicate_count = 0

    # Lista para guardar las líneas no procesadas (por formato incorrecto)
    remaining_lines = [] 

    with open(file_path,'r',encoding='utf-8') as f:
        lines = f.read().splitlines()
        
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue # Saltar líneas vacías

        if stripped_line.count(":") != 1: 
            remaining_lines.append(line)
            fail_count += 1
            continue # Debe haber exactamente un ':' (email:pass)

        try:
            # Separar los dos valores
            email, password = stripped_line.split(":", 1)
            email_lower = email.lower()

            # *** NUEVO: Lógica para evitar duplicados ***
            if email_lower in registered_emails:
                duplicate_count += 1
                continue # Saltar duplicados
            
            # Usamos el email como 'username' para el seguimiento interno
            new_account = {'username':email,'gmail':email,'password':password}
            accounts_data['available'].append(new_account)
            registered_emails.add(email_lower) # Añadir al set
            update_log(new_account,"ADDED")
            success_count += 1

        except Exception as e:
            # Si hay una excepción, la línea no se procesó correctamente
            remaining_lines.append(line) 
            print(f"Error procesando línea en import: {line}. Error: {e}")
            fail_count += 1

    save_accounts()

    # *** NUEVO: Eliminar o actualizar el archivo import_accounts.txt ***
    # Si quedan líneas sin procesar (por formato), se reescribe el archivo.
    # Si no queda ninguna, se elimina el archivo.
    if remaining_lines:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(remaining_lines) + '\n')
        await ctx.send(f"⚠️ **{fail_count}** líneas con formato incorrecto. Quedan en `{file_path}` para corrección.")
    else:
        # Si todo se procesó o se saltó por duplicado, eliminamos el archivo.
        remove_import_file(file_path)
    
    await ctx.send(
        f"✅ Importadas **{success_count}** cuentas correctamente.\n"
        f"🔄 Duplicadas (ya en inventario): **{duplicate_count}** (omitidas).\n"
        f"❌ Fallidas (formato incorrecto): **{fail_count}**."
    )


@add_account.error
async def add_account_error(ctx,error):
    """Maneja errores específicos del comando addaccount."""
    if isinstance(error, commands.MissingRequiredArgument):
        # Ahora solo se requieren 2 argumentos
        await ctx.send("❌ Uso incorrecto: `!addaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado. Solo administradores pueden usar este comando.")
    else:
        print(f"Error inesperado en add_account: {error}")
        await ctx.send("❌ Error al añadir la cuenta. Revisa la consola para más detalles.")

# --- Comando Sync para forzar sincronización ---
@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """Sincroniza los comandos de barra con Discord"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sincronizados {len(synced)} comandos de barra")
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        await ctx.send(f"❌ Error sincronizando comandos: {e}")
        print(f"Error sincronizando: {e}")

# --- Keep Alive para Replit ---

app = Flask('')
@app.route('/')
def home():
    """Ruta simple para mantener el bot activo en entornos como Replit."""
    return "Bot is running and ready!"

def run():
    """Ejecuta la aplicación Flask."""
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """Inicia el thread para mantener la aplicación web activa."""
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
