# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask
import asyncio
import aiohttp
import re
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import uuid

# Cargar variables de entorno
load_dotenv()

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

# URLs para autenticación
SFTTAG_URL = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"

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

# --- Funciones de Autenticación Microsoft (Completas) ---

async def get_urlPost_sFTTag(session):
    """Obtiene URL y token para autenticación Microsoft"""
    try:
        async with session.get(SFTTAG_URL, timeout=aiohttp.ClientTimeout(total=15)) as response:
            text = await response.text()
            match = re.search(r'value=\\\"(.+?)\\\"', text, re.S) or re.search(r'value="(.+?)"', text, re.S)
            if match:
                sFTTag = match.group(1)
                match = re.search(r'"urlPost":"(.+?)"', text, re.S) or re.search(r"urlPost:'(.+?)'", text, re.S)
                if match:
                    return match.group(1), sFTTag
    except Exception as e:
        print(f"❌ Error obteniendo URL de autenticación: {e}")
    return None, None

async def get_xbox_rps(session, email, password, urlPost, sFTTag):
    """Autentica con Microsoft y obtiene token"""
    try:
        data = {
            'login': email, 
            'loginfmt': email, 
            'passwd': password, 
            'PPFT': sFTTag
        }
        
        async with session.post(
            urlPost, 
            data=data, 
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            if '#' in str(response.url) and str(response.url) != SFTTAG_URL:
                token = parse_qs(urlparse(str(response.url)).fragment).get('access_token', ["None"])[0]
                if token != "None":
                    return token
            
            text = await response.text()
            
            if any(value in text for value in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt"]):
                return "2FA_REQUIRED"
            elif any(value in text.lower() for value in ["password is incorrect", "account doesn't exist", "sign in to your microsoft account"]):
                return "INVALID_CREDENTIALS"
                
    except Exception as e:
        return f"ERROR: {str(e)}"
    
    return "UNKNOWN_ERROR"

async def get_minecraft_profile(session, access_token):
    """Obtiene el perfil completo de Minecraft"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Obtener perfil básico
        async with session.get('https://api.minecraftservices.com/minecraft/profile', headers=headers) as response:
            if response.status == 200:
                profile_data = await response.json()
                
                # Obtener información de name change
                name_change_data = None
                async with session.get('https://api.minecraftservices.com/minecraft/profile/namechange', headers=headers) as name_response:
                    if name_response.status == 200:
                        name_change_data = await name_response.json()
                
                # Obtener entitlements (juegos poseídos)
                entitlements_data = None
                async with session.get('https://api.minecraftservices.com/entitlements/mcstore', headers=headers) as entitle_response:
                    if entitle_response.status == 200:
                        entitlements_data = await entitle_response.json()
                
                # Verificar capa de Optifine
                optifine_cape = await check_optifine_cape(session, profile_data.get('name'))
                
                return {
                    'profile': profile_data,
                    'name_change': name_change_data,
                    'entitlements': entitlements_data,
                    'optifine_cape': optifine_cape
                }
                
    except Exception as e:
        print(f"❌ Error obteniendo perfil Minecraft: {e}")
    
    return None

async def check_optifine_cape(session, username):
    """Verifica si el usuario tiene capa de Optifine"""
    if not username:
        return "Unknown"
    
    try:
        async with session.get(f'http://s.optifine.net/capes/{username}.png') as response:
            if response.status == 404:
                return "No"
            elif response.status == 200:
                return "Yes"
    except:
        pass
    
    return "Unknown"

async def get_xbox_live_token(session, microsoft_token):
    """Obtiene token de Xbox Live"""
    try:
        data = {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": f"d={microsoft_token}"
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT"
        }
        
        async with session.post(
            'https://user.auth.xboxlive.com/user/authenticate',
            json=data,
            headers={'Content-Type': 'application/json'}
        ) as response:
            if response.status == 200:
                return await response.json()
    except Exception as e:
        print(f"❌ Error obteniendo token Xbox Live: {e}")
    
    return None

async def get_xsts_token(session, xbox_token):
    """Obtiene token XSTS"""
    try:
        data = {
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [xbox_token]
            },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT"
        }
        
        async with session.post(
            'https://xsts.auth.xboxlive.com/xsts/authorize',
            json=data,
            headers={'Content-Type': 'application/json'}
        ) as response:
            if response.status == 200:
                return await response.json()
    except Exception as e:
        print(f"❌ Error obteniendo token XSTS: {e}")
    
    return None

async def get_minecraft_token(session, uhs, xsts_token):
    """Obtiene token de Minecraft"""
    try:
        data = {
            'identityToken': f"XBL3.0 x={uhs};{xsts_token}"
        }
        
        async with session.post(
            'https://api.minecraftservices.com/authentication/login_with_xbox',
            json=data,
            headers={'Content-Type': 'application/json'}
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('access_token')
    except Exception as e:
        print(f"❌ Error obteniendo token Minecraft: {e}")
    
    return None

async def verify_microsoft_account(email, password):
    """
    Verifica una cuenta de Microsoft y obtiene información completa.
    """
    try:
        # Validación básica
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

        # Crear sesión
        connector = aiohttp.TCPConnector(verify_ssl=False)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Paso 1: Obtener URL de autenticación
            urlPost, sFTTag = await get_urlPost_sFTTag(session)
            if not urlPost:
                return {
                    "success": False,
                    "error": "No se pudo obtener URL de autenticación"
                }

            # Paso 2: Autenticar con Microsoft
            microsoft_token = await get_xbox_rps(session, email, password, urlPost, sFTTag)
            
            if microsoft_token == "INVALID_CREDENTIALS":
                return {
                    "success": False,
                    "error": "Credenciales inválidas"
                }
            elif microsoft_token == "2FA_REQUIRED":
                return {
                    "success": False,
                    "error": "Autenticación de 2 factores requerida"
                }
            elif microsoft_token.startswith("ERROR"):
                return {
                    "success": False,
                    "error": microsoft_token
                }
            elif microsoft_token == "UNKNOWN_ERROR":
                return {
                    "success": False,
                    "error": "Error desconocido en autenticación"
                }

            # Paso 3: Obtener token Xbox Live
            xbox_data = await get_xbox_live_token(session, microsoft_token)
            if not xbox_data:
                return {
                    "success": False,
                    "error": "Error obteniendo token Xbox Live"
                }

            xbox_token = xbox_data.get('Token')
            uhs = xbox_data['DisplayClaims']['xui'][0]['uhs']

            # Paso 4: Obtener token XSTS
            xsts_data = await get_xsts_token(session, xbox_token)
            if not xsts_data:
                return {
                    "success": False,
                    "error": "Error obteniendo token XSTS"
                }

            xsts_token = xsts_data.get('Token')

            # Paso 5: Obtener token Minecraft
            minecraft_token = await get_minecraft_token(session, uhs, xsts_token)
            if not minecraft_token:
                return {
                    "success": False,
                    "error": "Error obteniendo token Minecraft"
                }

            # Paso 6: Obtener perfil completo
            profile_info = await get_minecraft_profile(session, minecraft_token)
            
            if not profile_info:
                return {
                    "success": True,
                    "email": email,
                    "password": password,
                    "has_minecraft": False,
                    "message": "✅ Cuenta verificada - Sin Minecraft"
                }

            # Procesar información del perfil
            profile_data = profile_info['profile']
            name_change_data = profile_info['name_change']
            entitlements_data = profile_info['entitlements']
            
            # Determinar tipo de cuenta
            account_type = "Normal"
            games_owned = []
            
            if entitlements_data:
                items = entitlements_data.get('items', [])
                for item in items:
                    name = item.get('name', '')
                    if 'game_pass_ultimate' in name:
                        account_type = "Xbox Game Pass Ultimate"
                    elif 'game_pass_pc' in name:
                        account_type = "Xbox Game Pass"
                    elif 'minecraft_bedrock' in name:
                        games_owned.append("Minecraft Bedrock")
                    elif 'legends' in name:
                        games_owned.append("Minecraft Legends")
                    elif 'dungeons' in name:
                        games_owned.append("Minecraft Dungeons")

            # Información de capas Minecraft
            capes = []
            if 'capes' in profile_data:
                for cape in profile_data['capes']:
                    capes.append(cape.get('alias', 'Unknown'))

            # Información de cambio de nombre
            name_changeable = "Unknown"
            if name_change_data:
                name_changeable = name_change_data.get('nameChangeAllowed', False)

            # Fecha de creación
            creation_date = "Unknown"
            if name_change_data and 'createdAt' in name_change_data:
                try:
                    created_at = name_change_data['createdAt']
                    # Formatear fecha
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    creation_date = dt.strftime("%A, %d de %B de %Y, %H:%M").lower()
                    # Traducir (simplificado)
                    creation_date = creation_date.replace('monday', 'lunes').replace('tuesday', 'martes').replace('wednesday', 'miércoles').replace('thursday', 'jueves').replace('friday', 'viernes').replace('saturday', 'sábado').replace('sunday', 'domingo').replace('january', 'enero').replace('february', 'febrero').replace('march', 'marzo').replace('april', 'abril').replace('may', 'mayo').replace('june', 'junio').replace('july', 'julio').replace('august', 'agosto').replace('september', 'septiembre').replace('october', 'octubre').replace('november', 'noviembre').replace('december', 'diciembre')
                except:
                    creation_date = "Unknown"

            return {
                "success": True,
                "email": email,
                "password": password,
                "has_minecraft": True,
                "message": "✅ Cuenta verificada exitosamente",
                "details": {
                    "username": profile_data.get('name', 'N/A'),
                    "uuid": profile_data.get('id', 'N/A'),
                    "account_type": account_type,
                    "capes": ", ".join(capes) if capes else "None",
                    "optifine_cape": profile_info['optifine_cape'],
                    "name_changeable": name_changeable,
                    "creation_date": creation_date,
                    "games_owned": ", ".join(games_owned) if games_owned else "None",
                    "access_token": minecraft_token
                }
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error durante la verificación: {str(e)}"
        }

# --- Funciones Auxiliares del Bot ---

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
                print(f"✅ Cuentas cargadas: {len(bot.accounts_data['available'])} disponibles")
                return True
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
    """Añade una entrada al archivo de registro."""
    log_entry = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"STATUS: {status} | Email: {account_info['gmail']}\n"
    )
    try:
        with open(LOGS_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"❌ Error escribiendo log: {e}")

# --- Tasks y Eventos ---

@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    print(f'🤖 Bot conectado como {bot.user}!')
    load_accounts()
    
    if not distribute_account.is_running():
        distribute_account.start()
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(bot.accounts_data['available'])} cuentas"
        )
    )

@tasks.loop(minutes=DISTRIBUTION_INTERVAL_MINUTES)
async def distribute_account():
    """Distribuye cuentas en el canal configurado."""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel or not bot.accounts_data['available']:
            return

        account = bot.accounts_data['available'].pop(0)

        embed = discord.Embed(
            title=f"✨ Cuenta Disponible ✨",
            description="Reacciona para indicar el estado:",
            color=0x00ff00
        )
        embed.add_field(name="📧 Correo", value=f"`{account['gmail']}`", inline=False)
        embed.add_field(name="🔒 Contraseña", value=f"`{account['password']}`", inline=False)
        
        # Añadir información adicional si existe
        if 'username' in account and account['username'] != 'N/A':
            embed.add_field(name="🎮 Usuario", value=account['username'], inline=True)
        if 'account_type' in account:
            embed.add_field(name="📦 Tipo", value=account['account_type'], inline=True)
        
        embed.set_footer(text=f"✅ Usada | ❌ Error | 🚨 Bloqueada | {len(bot.accounts_data['available'])} restantes")

        message = await channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")
        await message.add_reaction("🚨")

        account_distributed = account.copy()
        account_distributed['message_id'] = message.id
        account_distributed['distribution_date'] = datetime.now().isoformat()
        account_distributed['reactions'] = {'✅': 0, '❌': 0, '🚨': 0, 'users': []}
        bot.accounts_data['distributed'].append(account_distributed)
        
        save_accounts()
        update_log(account, "DISTRIBUTED")
        
    except Exception as e:
        print(f"❌ Error distribuyendo cuenta: {e}")

# --- Comandos ---

@bot.command(name='verifyaccount')
@commands.has_permissions(administrator=True)
async def verify_account(ctx, email: str, password: str):
    """Verifica una cuenta de Microsoft y muestra información detallada."""
    processing_msg = await ctx.send("🔄 Verificando cuenta Microsoft... Esto puede tomar unos segundos.")
    
    try:
        result = await verify_microsoft_account(email, password)
        
        if result["success"]:
            if result.get("has_minecraft", False):
                details = result["details"]
                
                embed = discord.Embed(
                    title="✅ CUENTA VERIFICADA - MINECRAFT DETECTADO",
                    color=0x00ff00
                )
                
                # Información básica
                embed.add_field(
                    name="📧 Credenciales", 
                    value=f"**Email:** `{email}`\n**Password:** `{password}`", 
                    inline=False
                )
                
                # Información de la cuenta
                embed.add_field(
                    name="👤 Información de Cuenta",
                    value=f"**Usuario:** {details['username']}\n**UUID:** `{details['uuid']}`\n**Tipo:** {details['account_type']}",
                    inline=False
                )
                
                # Capas y personalización
                cape_info = f"**Capas Minecraft:** {details['capes']}\n**Capa Optifine:** {details['optifine_cape']}\n**Puede cambiar nombre:** {details['name_changeable']}"
                embed.add_field(name="🎨 Personalización", value=cape_info, inline=False)
                
                # Fecha y juegos
                extra_info = f"**Fecha de creación:** {details['creation_date']}\n**Otros juegos:** {details['games_owned']}"
                embed.add_field(name="📅 Información Adicional", value=extra_info, inline=False)
                
                embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar")
                
            else:
                # Cuenta sin Minecraft
                embed = discord.Embed(
                    title="✅ CUENTA VERIFICADA - SIN MINECRAFT",
                    color=0xffff00
                )
                embed.add_field(name="📧 Email", value=email, inline=False)
                embed.add_field(name="🔒 Contraseña", value=password, inline=False)
                embed.add_field(name="💡 Estado", value="Cuenta Microsoft válida pero sin Minecraft", inline=False)
                embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar")
            
            message = await ctx.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")
            
            bot.temp_verified_accounts[message.id] = {
                "email": email,
                "password": password,
                **result
            }
            
        else:
            embed = discord.Embed(
                title="❌ ERROR EN VERIFICACIÓN",
                color=0xff0000
            )
            embed.add_field(name="📧 Email", value=email, inline=False)
            embed.add_field(name="🔒 Contraseña", value=password, inline=False)
            embed.add_field(name="❌ Error", value=result["error"], inline=False)
            await ctx.send(embed=embed)
    
    except Exception as e:
        embed = discord.Embed(
            title="❌ ERROR INESPERADO",
            description=f"Ocurrió un error: {str(e)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    
    finally:
        await processing_msg.delete()

@bot.command(name='addaccount')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """Añade una cuenta al inventario."""
    email_lower = email.lower()

    if email_lower in bot.registered_emails:
        await ctx.send("❌ Esta cuenta ya existe en el inventario.")
        return

    new_account = {
        'username': email,
        'gmail': email, 
        'password': password,
        'added_date': datetime.now().isoformat()
    }
    
    bot.accounts_data['available'].append(new_account)
    bot.registered_emails.add(email_lower)
    save_accounts()

    embed = discord.Embed(
        title="✅ Cuenta Añadida",
        color=0x00ff00
    )
    embed.add_field(name="📧 Correo", value=email)
    embed.add_field(name="📊 Inventario", value=f"{len(bot.accounts_data['available'])} disponibles")
    await ctx.send(embed=embed)

@bot.command(name='stats')
async def stats(ctx):
    """Muestra estadísticas del inventario."""
    embed = discord.Embed(title="📊 Estadísticas", color=0x0099ff)
    embed.add_field(name="📥 Disponibles", value=len(bot.accounts_data['available']), inline=True)
    embed.add_field(name="📤 Distribuidas", value=len(bot.accounts_data['distributed']), inline=True)
    await ctx.send(embed=embed)

# Manejo de reacciones para verificación
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    # Manejar verificación de cuentas
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
                
                # Añadir detalles si la cuenta tiene Minecraft
                if account_data.get("has_minecraft") and "details" in account_data:
                    new_account.update(account_data["details"])
                
                bot.accounts_data['available'].append(new_account)
                bot.registered_emails.add(email_lower)
                save_accounts()
                
                await reaction.message.reply("✅ Cuenta añadida al inventario!")
                
                # Actualizar presencia
                await bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f"{len(bot.accounts_data['available'])} cuentas"
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

# --- Keep Alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot de Cuentas Microsoft - En línea"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# --- Ejecución ---
if __name__ == '__main__':
    keep_alive()
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Error: {e}")
