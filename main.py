# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask
import requests
import re
import urllib3
from urllib.parse import urlparse, parse_qs
import uuid

# --- Configuración Inicial ---
TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
DISTRIBUTION_INTERVAL_MINUTES = 10.0

# --- Rutas de Archivos ---
DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')

# Deshabilitar warnings de SSL
urllib3.disable_warnings()

# URL para autenticación Microsoft
sFTTag_url = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"

# Asegurarse de que las carpetas y archivos existan
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

for file_path in [ACCOUNTS_FILE, LOGS_FILE]:
    if not os.path.exists(file_path):
        if file_path.endswith('.json'):
            # Inicializar el archivo JSON con las estructuras necesarias
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
bot = commands.Bot(command_prefix='!', intents=intents)

# Cargar los datos de las cuentas al iniciar
accounts_data = {'available': [], 'distributed': []}
# Conjunto para una búsqueda rápida de emails ya registrados
registered_emails = set()

# --- Funciones de Autenticación Microsoft (del checker) ---

def get_urlPost_sFTTag(session):
    """Obtiene URL y token para autenticación Microsoft"""
    while True:
        try:
            text = session.get(sFTTag_url, timeout=15).text
            match = re.search(r'value=\\\"(.+?)\\\"', text, re.S) or re.search(r'value="(.+?)"', text, re.S)
            if match:
                sFTTag = match.group(1)
                match = re.search(r'"urlPost":"(.+?)"', text, re.S) or re.search(r"urlPost:'(.+?)'", text, re.S)
                if match:
                    return match.group(1), sFTTag, session
        except Exception:
            pass
        return None, None, session

def get_xbox_rps(session, email, password, urlPost, sFTTag):
    """Autentica con Microsoft y obtiene token"""
    try:
        data = {'login': email, 'loginfmt': email, 'passwd': password, 'PPFT': sFTTag}
        login_request = session.post(urlPost, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'}, allow_redirects=True, timeout=15)
        
        if '#' in login_request.url and login_request.url != sFTTag_url:
            token = parse_qs(urlparse(login_request.url).fragment).get('access_token', ["None"])[0]
            if token != "None":
                return token, session
        elif any(value in login_request.text for value in ["password is incorrect", r"account doesn\'t exist.", "sign in to your microsoft account"]):
            return "INVALID_CREDENTIALS", session
        elif any(value in login_request.text for value in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt"]):
            return "2FA_REQUIRED", session
    except Exception as e:
        return f"ERROR: {str(e)}", session
    
    return "UNKNOWN_ERROR", session

def get_minecraft_profile(session, access_token):
    """Obtiene el perfil de Minecraft"""
    try:
        r = session.get('https://api.minecraftservices.com/minecraft/profile', 
                       headers={'Authorization': f'Bearer {access_token}'}, 
                       verify=False)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def authenticate_microsoft_account(email, password):
    """Autentica una cuenta de Microsoft y obtiene información del perfil"""
    try:
        session = requests.Session()
        session.verify = False
        
        # Paso 1: Obtener URL de autenticación
        urlPost, sFTTag, session = get_urlPost_sFTTag(session)
        if not urlPost:
            return {"success": False, "error": "No se pudo obtener URL de autenticación"}
        
        # Paso 2: Autenticar con Microsoft
        token, session = get_xbox_rps(session, email, password, urlPost, sFTTag)
        
        if token == "INVALID_CREDENTIALS":
            return {"success": False, "error": "Credenciales inválidas"}
        elif token == "2FA_REQUIRED":
            return {"success": False, "error": "Autenticación de 2 factores requerida"}
        elif token.startswith("ERROR"):
            return {"success": False, "error": token}
        elif token == "UNKNOWN_ERROR":
            return {"success": False, "error": "Error desconocido en autenticación"}
        
        # Paso 3: Obtener perfil de Minecraft si el token es válido
        profile = get_minecraft_profile(session, token)
        
        result = {
            "success": True,
            "email": email,
            "password": password,
            "access_token": token,
            "profile": profile
        }
        
        if profile:
            result["minecraft_username"] = profile.get('name', 'N/A')
            result["uuid"] = profile.get('id', 'N/A')
            result["capes"] = ", ".join([cape["alias"] for cape in profile.get("capes", [])])
        
        return result
        
    except Exception as e:
        return {"success": False, "error": f"Error en autenticación: {str(e)}"}
    finally:
        session.close()

# --- Funciones Auxiliares del Bot ---

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

def remove_import_file(file_path):
    """Elimina el archivo de importación de cuentas."""
    try:
        os.remove(file_path)
        print(f"Archivo de importación eliminado: {file_path}")
    except Exception as e:
        print(f"Error al eliminar archivo {file_path}: {e}")

# --- Tasks y Eventos ---

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f'🤖 Bot conectado como {bot.user}!')
    load_accounts()
    # Iniciar el bucle de distribución
    distribute_account.start()

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
    
    # Añadir información adicional si está disponible
    if 'minecraft_username' in account_to_distribute and account_to_distribute['minecraft_username'] != 'N/A':
        embed.add_field(name="🎮 Usuario Minecraft", value=account_to_distribute['minecraft_username'], inline=True)
    if 'capes' in account_to_distribute and account_to_distribute['capes']:
        embed.add_field(name="🧥 Capas", value=account_to_distribute['capes'], inline=True)
    
    embed.set_footer(text=f"Reacciona: ✅ Usada | ❌ Error Credenciales | 🚨 Cuenta No Sirve/Bloqueada | {len(accounts_data['available'])} restantes.")

    try:
        # Enviar el mensaje y añadir las tres reacciones
        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("🚨")

        # Guardar la información de la distribución
        account_data_distributed = account_to_distribute.copy()
        account_data_distributed['distribution_date'] = datetime.now().isoformat()
        account_data_distributed['message_id'] = message.id
        account_data_distributed['reactions'] = {'✅':0,'❌':0,'🚨':0,'users':[]}
        accounts_data['distributed'].append(account_data_distributed)
        
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

# --- Comandos ---

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """
    Añade una cuenta al inventario, usando el email como identificador principal.
    """
    email_lower = email.lower()

    # Chequeo de duplicados al añadir manualmente
    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta con correo **{email}** ya existe en el inventario.")
        return

    await ctx.send("✅ Recibida la información.")

    # El campo 'username' se utiliza internamente para mantener la estructura,
    # pero ahora guarda el email.
    new_account = {'username': email, 'gmail': email, 'password': password}
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower) # Añadir al set
    save_accounts()
    update_log(new_account, "ADDED")

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

@bot.command(name='verifyaccount', help='Verifica y extrae información de una cuenta Microsoft. Formato: !verifyaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def verify_account(ctx, email: str, password: str):
    """
    Verifica una cuenta de Microsoft y extrae información del perfil usando autenticación.
    """
    # Mostrar mensaje de procesamiento
    processing_msg = await ctx.send("🔄 Verificando cuenta Microsoft... Esto puede tomar unos segundos.")
    
    try:
        # Autenticar la cuenta
        result = authenticate_microsoft_account(email, password)
        
        if result["success"]:
            # Crear embed con la información obtenida
            embed = discord.Embed(
                title="✅ Cuenta Verificada Exitosamente",
                description="La cuenta ha sido verificada y está lista para ser añadida al inventario.",
                color=discord.Color.green()
            )
            
            embed.add_field(name="📧 Correo", value=email, inline=False)
            embed.add_field(name="🔒 Contraseña", value=password, inline=False)
            
            if result.get("minecraft_username") and result["minecraft_username"] != "N/A":
                embed.add_field(name="🎮 Usuario Minecraft", value=result["minecraft_username"], inline=True)
                embed.add_field(name="🆔 UUID", value=result.get("uuid", "N/A"), inline=True)
            
            if result.get("capes"):
                embed.add_field(name="🧥 Capas", value=result["capes"], inline=False)
            
            embed.add_field(name="🔑 Token Válido", value="Sí", inline=True)
            
            # Preguntar si desea añadir la cuenta al inventario
            embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar.")
            
            message = await ctx.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")
            
            # Guardar datos temporalmente para usar en la reacción
            ctx.bot.temp_verified_account = {
                "email": email,
                "password": password,
                "minecraft_username": result.get("minecraft_username", "N/A"),
                "capes": result.get("capes", ""),
                "message_id": message.id
            }
            
        else:
            # Mostrar error
            embed = discord.Embed(
                title="❌ Error en Verificación",
                description="No se pudo verificar la cuenta.",
                color=discord.Color.red()
            )
            embed.add_field(name="📧 Correo", value=email, inline=False)
            embed.add_field(name="🔒 Contraseña", value=password, inline=False)
            embed.add_field(name="❌ Error", value=result["error"], inline=False)
            
            await ctx.send(embed=embed)
    
    except Exception as e:
        await ctx.send(f"❌ Error inesperado durante la verificación: {str(e)}")
    
    finally:
        # Eliminar mensaje de procesamiento
        await processing_msg.delete()

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

            # Lógica para evitar duplicados
            if email_lower in registered_emails:
                duplicate_count += 1
                continue # Saltar duplicados
            
            # Usamos el email como 'username' para el seguimiento interno
            new_account = {'username': email, 'gmail': email, 'password': password}
            accounts_data['available'].append(new_account)
            registered_emails.add(email_lower) # Añadir al set
            update_log(new_account, "ADDED")
            success_count += 1

        except Exception as e:
            # Si hay una excepción, la línea no se procesó correctamente
            remaining_lines.append(line) 
            print(f"Error procesando línea en import: {line}. Error: {e}")
            fail_count += 1

    save_accounts()

    # Eliminar o actualizar el archivo import_accounts.txt
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

# Manejar reacciones para el comando verifyaccount
@bot.event
async def on_reaction_add(reaction, user):
    """Maneja las reacciones a los mensajes de distribución y verificación."""
    if user.bot:
        return

    # Verificar si es una reacción de verificación de cuenta
    if hasattr(reaction, 'message') and hasattr(reaction.message, 'id'):
        message_id = reaction.message.id
        
        # Buscar si es un mensaje de verificación temporal
        if hasattr(bot, 'temp_verified_account') and bot.temp_verified_account.get('message_id') == message_id:
            if str(reaction.emoji) == "✅" and user != bot.user:
                account_data = bot.temp_verified_account
                email_lower = account_data["email"].lower()
                
                # Verificar que no sea duplicado
                if email_lower not in registered_emails:
                    # Crear cuenta con información adicional
                    new_account = {
                        'username': account_data["email"],
                        'gmail': account_data["email"], 
                        'password': account_data["password"]
                    }
                    
                    # Añadir información de Minecraft si está disponible
                    if account_data.get("minecraft_username") and account_data["minecraft_username"] != "N/A":
                        new_account['minecraft_username'] = account_data["minecraft_username"]
                    if account_data.get("capes"):
                        new_account['capes'] = account_data["capes"]
                    
                    accounts_data['available'].append(new_account)
                    registered_emails.add(email_lower)
                    save_accounts()
                    update_log(new_account, "ADDED_VERIFIED")
                    
                    # Enviar confirmación
                    embed = discord.Embed(
                        title="✅ Cuenta Añadida al Inventario",
                        description="La cuenta verificada ha sido añadida exitosamente.",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="📧 Correo", value=account_data["email"])
                    embed.add_field(name="🎮 Usuario Minecraft", value=account_data.get("minecraft_username", "N/A"))
                    embed.add_field(name="📊 Inventario Total", value=f"{len(accounts_data['available'])} disponibles")
                    
                    await reaction.message.reply(embed=embed)
                else:
                    await reaction.message.reply("❌ Esta cuenta ya existe en el inventario.")
                
                # Limpiar datos temporales
                del bot.temp_verified_account
                await reaction.message.clear_reactions()
            
            elif str(reaction.emoji) == "❌" and user != bot.user:
                await reaction.message.reply("❌ Cuenta descartada.")
                # Limpiar datos temporales
                del bot.temp_verified_account
                await reaction.message.clear_reactions()
            
            return

    # Código existente para manejar reacciones de distribución...
    valid_emojis = ["✅","❌", "🚨"]
    
    if reaction.message.channel.id != CHANNEL_ID or str(reaction.emoji) not in valid_emojis:
        return

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

@add_account.error
async def add_account_error(ctx,error):
    """Maneja errores específicos del comando addaccount."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorrecto: `!addaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado. Solo administradores pueden usar este comando.")
    else:
        print(f"Error inesperado en add_account: {error}")
        await ctx.send("❌ Error al añadir la cuenta. Revisa la consola para más detalles.")

@verify_account.error
async def verify_account_error(ctx,error):
    """Maneja errores específicos del comando verifyaccount."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorrecto: `!verifyaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado. Solo administradores pueden usar este comando.")
    else:
        print(f"Error inesperado en verify_account: {error}")
        await ctx.send("❌ Error al verificar la cuenta. Revisa la consola para más detalles.")

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
