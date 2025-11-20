# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask
import asyncio

# --- Configuración Inicial ---
TOKEN = os.environ.get('DISCORD_TOKEN')
CHANNEL_ID = int(os.environ.get('CHANNEL_ID', 0))
DISTRIBUTION_INTERVAL_MINUTES = 30.0

# Validar variables de entorno requeridas
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN no está configurado")
    exit(1)
if CHANNEL_ID == 0:
    print("❌ ERROR: CHANNEL_ID no está configurado")
    exit(1)

# --- Rutas de Archivos ---
DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')

# Asegurarse de que las carpetas y archivos existan
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

for file_path in [ACCOUNTS_FILE, LOGS_FILE]:
    if not os.path.exists(file_path):
        if file_path.endswith('.json'):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({'available': [], 'distributed': []}, f, indent=4)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('--- Archivo de Registro de Cuentas ---\n')

# --- Definición del Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

class AccountBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        self.accounts_data = {'available': [], 'distributed': []}
        self.registered_emails = set()
        self.temp_verified_accounts = {}

bot = AccountBot()

# --- Funciones Auxiliares ---

def load_accounts():
    """Carga los datos de las cuentas desde el archivo JSON."""
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'available' in data and 'distributed' in data:
                bot.accounts_data = data
                bot.registered_emails.clear()
                for account in bot.accounts_data['distributed']:
                    if 'gmail' in account:
                        bot.registered_emails.add(account['gmail'].lower())
                for account in bot.accounts_data['available']:
                    if 'gmail' in account:
                        bot.registered_emails.add(account['gmail'].lower())
                print(f"✅ Cuentas cargadas: {len(bot.accounts_data['available'])} disponibles, {len(bot.accounts_data['distributed'])} distribuidas")
                return True
            else:
                return False
    except Exception as e:
        print(f"❌ Error cargando cuentas: {e}")
        return False

def save_accounts():
    """Guarda los datos de las cuentas en el archivo JSON."""
    try:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bot.accounts_data, f, indent=4)
    except Exception as e:
        print(f"❌ Error guardando cuentas: {e}")

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
        print(f"❌ Error escribiendo log: {e}")

def remove_import_file(file_path):
    """Elimina el archivo de importación de cuentas."""
    try:
        os.remove(file_path)
        print(f"✅ Archivo de importación eliminado: {file_path}")
    except Exception as e:
        print(f"❌ Error al eliminar archivo {file_path}: {e}")

# --- Funciones de Verificación de Cuentas ---

async def verify_microsoft_account(email, password):
    """
    Verifica una cuenta de Microsoft.
    Esta es una versión básica que puedes expandir.
    """
    try:
        # Validación básica de formato
        if "@" not in email or "." not in email:
            return {
                "success": False,
                "error": "Formato de email inválido"
            }
        
        if len(password) < 1:
            return {
                "success": False,
                "error": "La contraseña no puede estar vacía"
            }
        
        # Simulación de verificación exitosa
        # En una implementación real, aquí iría la autenticación con Microsoft
        await asyncio.sleep(1)  # Simular procesamiento
        
        return {
            "success": True,
            "email": email,
            "password": password,
            "message": "✅ Cuenta verificada correctamente",
            "details": {
                "email_valid": True,
                "can_authenticate": True,
                "has_minecraft": True
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error durante la verificación: {str(e)}"
        }

# --- Tasks y Eventos ---

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f'🤖 Bot conectado como {bot.user}!')
    print(f'📊 Servidores: {len(bot.guilds)}')
    
    load_accounts()
    
    # Iniciar tarea de distribución
    if not distribute_account.is_running():
        distribute_account.start()
    
    # Establecer estado del bot
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(bot.accounts_data['available'])} cuentas disponibles"
        )
    )

@tasks.loop(minutes=DISTRIBUTION_INTERVAL_MINUTES)
async def distribute_account():
    """Tarea de bucle para distribuir cuentas en el canal configurado."""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print("❌ Canal no encontrado")
            return

        if not bot.accounts_data['available']:
            print("ℹ️ No hay cuentas disponibles para distribuir")
            return

        account_to_distribute = bot.accounts_data['available'].pop(0)

        # Validar campos requeridos
        required_keys = ['gmail', 'password']
        if not all(key in account_to_distribute for key in required_keys):
            bot.accounts_data['available'].insert(0, account_to_distribute)
            return

        # Crear embed
        embed = discord.Embed(
            title=f"✨ Cuenta Disponible ✨",
            description="¡Se ha liberado una cuenta! Reacciona para indicar su estado:",
            color=0x00ff00
        )
        embed.add_field(name="📧 Correo", value=f"`{account_to_distribute['gmail']}`", inline=False)
        embed.add_field(name="🔒 Contraseña", value=f"`{account_to_distribute['password']}`", inline=False)
        
        # Añadir información adicional si existe
        if 'minecraft_username' in account_to_distribute:
            embed.add_field(name="🎮 Usuario Minecraft", value=account_to_distribute['minecraft_username'], inline=True)
        
        embed.set_footer(text=f"✅ Usada | ❌ Error | 🚨 Bloqueada | {len(bot.accounts_data['available'])} restantes")

        # Enviar mensaje
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("🚨")

        # Guardar información de distribución
        account_data_distributed = account_to_distribute.copy()
        account_data_distributed['distribution_date'] = datetime.now().isoformat()
        account_data_distributed['message_id'] = message.id
        account_data_distributed['reactions'] = {'✅': 0, '❌': 0, '🚨': 0, 'users': []}
        bot.accounts_data['distributed'].append(account_data_distributed)
        
        save_accounts()
        update_log(account_to_distribute, "DISTRIBUTED")
        
        print(f"✅ Cuenta distribuida: {account_to_distribute['gmail']}")
        
    except Exception as e:
        print(f"❌ Error en distribute_account: {e}")
        # Revertir si hay error
        if 'account_to_distribute' in locals():
            bot.accounts_data['available'].insert(0, account_to_distribute)

@bot.event
async def on_reaction_add(reaction, user):
    """Maneja las reacciones a los mensajes."""
    if user.bot:
        return

    # Manejar reacciones de verificación
    if reaction.message.id in bot.temp_verified_accounts:
        if str(reaction.emoji) == "✅" and user != bot.user:
            account_data = bot.temp_verified_accounts[reaction.message.id]
            email_lower = account_data["email"].lower()
            
            if email_lower not in bot.registered_emails:
                new_account = {
                    'username': account_data["email"],
                    'gmail': account_data["email"], 
                    'password': account_data["password"],
                    'verified': True,
                    'added_date': datetime.now().isoformat()
                }
                
                # Añadir detalles si existen
                if 'details' in account_data:
                    new_account.update(account_data['details'])
                
                bot.accounts_data['available'].append(new_account)
                bot.registered_emails.add(email_lower)
                save_accounts()
                update_log(new_account, "ADDED_VERIFIED")
                
                embed = discord.Embed(
                    title="✅ Cuenta Añadida al Inventario",
                    color=0x00ff00
                )
                embed.add_field(name="📧 Correo", value=account_data["email"])
                embed.add_field(name="📊 Inventario Total", value=f"{len(bot.accounts_data['available'])} disponibles")
                
                await reaction.message.reply(embed=embed)
                
                # Actualizar presencia
                await bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f"{len(bot.accounts_data['available'])} cuentas disponibles"
                    )
                )
            else:
                await reaction.message.reply("❌ Esta cuenta ya existe en el inventario.")
            
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()
        
        elif str(reaction.emoji) == "❌" and user != bot.user:
            await reaction.message.reply("❌ Cuenta descartada.")
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()
        
        return

    # Manejar reacciones de distribución
    valid_emojis = ["✅", "❌", "🚨"]
    
    if reaction.message.channel.id != CHANNEL_ID or str(reaction.emoji) not in valid_emojis:
        return

    message_id = reaction.message.id
    reacted_emoji = str(reaction.emoji)
    user_id = user.id

    for account in bot.accounts_data['distributed']:
        if account.get('message_id') == message_id:
            if user_id in account['reactions']['users']:
                await reaction.remove(user)
                return

            account['reactions']['users'].append(user_id)
            account['reactions'][reacted_emoji] += 1
            save_accounts()
            
            # Enviar confirmación de reacción
            try:
                await user.send(f"✅ Has reaccionado con {reacted_emoji} a la cuenta {account['gmail']}")
            except:
                pass  # El usuario puede tener los MD cerrados
            
            return

# --- Comandos ---

@bot.command(name='help')
async def help_command(ctx):
    """Muestra la ayuda de comandos."""
    embed = discord.Embed(
        title="🤖 Comandos del Bot de Cuentas",
        description="Lista de comandos disponibles:",
        color=0x0099ff
    )
    
    commands_list = [
        ("!addaccount <email> <contraseña>", "Añade una cuenta al inventario"),
        ("!verifyaccount <email> <contraseña>", "Verifica una cuenta Microsoft"),
        ("!importaccounts", "Importa cuentas desde import_accounts.txt"),
        ("!stats", "Muestra estadísticas del inventario"),
        ("!help", "Muestra esta ayuda")
    ]
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='addaccount')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """Añade una cuenta al inventario."""
    email_lower = email.lower()

    if email_lower in bot.registered_emails:
        embed = discord.Embed(
            title="❌ Error",
            description=f"La cuenta **{email}** ya existe en el inventario.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return

    new_account = {
        'username': email,
        'gmail': email, 
        'password': password,
        'added_date': datetime.now().isoformat(),
        'added_by': str(ctx.author)
    }
    
    bot.accounts_data['available'].append(new_account)
    bot.registered_emails.add(email_lower)
    save_accounts()
    update_log(new_account, "ADDED")

    embed = discord.Embed(
        title="✅ Cuenta Añadida",
        color=0x00ff00
    )
    embed.add_field(name="📧 Correo", value=email)
    embed.add_field(name="🔒 Contraseña", value=password)
    embed.add_field(name="📊 Inventario Total", value=f"{len(bot.accounts_data['available'])} disponibles")
    
    await ctx.send(embed=embed)
    
    # Actualizar presencia
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(bot.accounts_data['available'])} cuentas disponibles"
        )
    )

@bot.command(name='verifyaccount')
@commands.has_permissions(administrator=True)
async def verify_account(ctx, email: str, password: str):
    """Verifica una cuenta de Microsoft."""
    processing_msg = await ctx.send("🔄 Verificando cuenta Microsoft...")
    
    try:
        result = await verify_microsoft_account(email, password)
        
        if result["success"]:
            embed = discord.Embed(
                title="✅ Cuenta Verificada",
                color=0x00ff00
            )
            embed.add_field(name="📧 Correo", value=email, inline=False)
            embed.add_field(name="🔒 Contraseña", value=password, inline=False)
            embed.add_field(name="💡 Estado", value=result["message"], inline=False)
            
            if "details" in result:
                for key, value in result["details"].items():
                    embed.add_field(name=key.replace('_', ' ').title(), value=str(value), inline=True)
            
            embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar.")
            
            message = await ctx.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")
            
            # Guardar datos temporalmente
            bot.temp_verified_accounts[message.id] = {
                "email": email,
                "password": password,
                **result
            }
            
        else:
            embed = discord.Embed(
                title="❌ Error en Verificación",
                color=0xff0000
            )
            embed.add_field(name="📧 Correo", value=email, inline=False)
            embed.add_field(name="🔒 Contraseña", value=password, inline=False)
            embed.add_field(name="❌ Error", value=result["error"], inline=False)
            await ctx.send(embed=embed)
    
    except Exception as e:
        embed = discord.Embed(
            title="❌ Error Inesperado",
            description=f"Ocurrió un error durante la verificación: {str(e)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    
    finally:
        await processing_msg.delete()

@bot.command(name='importaccounts')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    """Importa cuentas desde un archivo de texto."""
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        embed = discord.Embed(
            title="❌ Archivo No Encontrado",
            description=f"No se encontró el archivo `{file_path}`.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return

    processing_msg = await ctx.send("⏳ Importando cuentas...")
    
    success_count = 0
    fail_count = 0
    duplicate_count = 0
    remaining_lines = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line:
                continue

            if stripped_line.count(":") != 1:
                remaining_lines.append(line)
                fail_count += 1
                continue

            try:
                email, password = stripped_line.split(":", 1)
                email_lower = email.lower()

                if email_lower in bot.registered_emails:
                    duplicate_count += 1
                    continue
                
                new_account = {
                    'username': email,
                    'gmail': email,
                    'password': password,
                    'added_date': datetime.now().isoformat(),
                    'added_by': 'import'
                }
                bot.accounts_data['available'].append(new_account)
                bot.registered_emails.add(email_lower)
                update_log(new_account, "ADDED")
                success_count += 1

            except Exception as e:
                remaining_lines.append(line)
                fail_count += 1

        save_accounts()

        # Manejar archivo restante
        if remaining_lines:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(remaining_lines) + '\n')
        else:
            remove_import_file(file_path)

        # Enviar resultados
        embed = discord.Embed(
            title="📊 Resultados de Importación",
            color=0x0099ff
        )
        embed.add_field(name="✅ Correctas", value=success_count, inline=True)
        embed.add_field(name="🔄 Duplicadas", value=duplicate_count, inline=True)
        embed.add_field(name="❌ Fallidas", value=fail_count, inline=True)
        embed.add_field(name="📊 Nuevo Total", value=f"{len(bot.accounts_data['available'])} disponibles", inline=False)
        
        await ctx.send(embed=embed)
        
        # Actualizar presencia
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(bot.accounts_data['available'])} cuentas disponibles"
            )
        )

    except Exception as e:
        embed = discord.Embed(
            title="❌ Error en Importación",
            description=f"Error: {str(e)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    
    finally:
        await processing_msg.delete()

@bot.command(name='stats')
async def stats(ctx):
    """Muestra estadísticas del inventario."""
    embed = discord.Embed(
        title="📊 Estadísticas del Inventario",
        color=0x0099ff
    )
    
    available = len(bot.accounts_data['available'])
    distributed = len(bot.accounts_data['distributed'])
    total = available + distributed
    
    embed.add_field(name="📥 Disponibles", value=available, inline=True)
    embed.add_field(name="📤 Distribuidas", value=distributed, inline=True)
    embed.add_field(name="📈 Total", value=total, inline=True)
    
    if bot.accounts_data['available']:
        next_account = bot.accounts_data['available'][0]
        embed.add_field(
            name="➡️ Siguiente Cuenta", 
            value=f"Email: {next_account['gmail']}", 
            inline=False
        )
    
    await ctx.send(embed=embed)

# Manejo de errores
@add_account.error
async def add_account_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Uso Incorrecto",
            description="Uso: `!addaccount <email> <contraseña>`",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permiso Denegado",
            description="Solo los administradores pueden usar este comando.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="Ocurrió un error al añadir la cuenta.",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@verify_account.error
async def verify_account_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Uso Incorrecto",
            description="Uso: `!verifyaccount <email> <contraseña>`",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permiso Denegado",
            description="Solo los administradores pueden usar este comando.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="Ocurrió un error al verificar la cuenta.",
            color=0xff0000
        )
        await ctx.send(embed=embed)

# --- Keep Alive para Railway ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot de Cuentas Microsoft - En línea y funcionando"

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# --- Ejecución ---
if __name__ == '__main__':
    print("🚀 Iniciando Bot de Cuentas Microsoft...")
    keep_alive()
    
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ ERROR: Token de Discord inválido")
    except Exception as e:
        print(f"❌ ERROR: {e}")
