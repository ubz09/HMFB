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

# --- Funciones de Autenticación Microsoft Mejoradas ---

async def microsoft_login(session, email, password):
    """Autenticación mejorada con Microsoft"""
    try:
        # Paso 1: Obtener página de login
        auth_url = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"
        
        async with session.get(auth_url) as response:
            text = await response.text()
            
            # Extraer PPFT token
            ppft_match = re.search(r'value="([^"]*)" id="i0327"', text)
            if not ppft_match:
                ppft_match = re.search(r'name="PPFT" value="([^"]*)"', text)
            
            if not ppft_match:
                return {"success": False, "error": "No se pudo obtener token de autenticación"}
            
            ppft = ppft_match.group(1)
            
            # Extraer URL Post
            url_post_match = re.search(r'urlPost:\'([^\']*)\'', text)
            if not url_post_match:
                return {"success": False, "error": "No se pudo obtener URL de envío"}
            
            url_post = url_post_match.group(1)

        # Paso 2: Enviar credenciales
        login_data = {
            'login': email,
            'loginfmt': email,
            'passwd': password,
            'PPFT': ppft,
            'type': '11',
            'NewUser': '1',
            'LoginOptions': '1',
            'i3': '36728',
            'm1': '768',
            'm2': '1184',
            'm3': '0',
            'i12': '1',
            'i17': '0',
            'i18': '__Login_Strings|1,__Login_Core|1,'
        }

        async with session.post(
            url_post,
            data=login_data,
            allow_redirects=False,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        ) as response:
            if response.status == 302:  # Redirección exitosa
                location = response.headers.get('Location', '')
                if 'access_token' in location:
                    # Extraer token de la URL
                    parsed = urlparse(location)
                    fragment = parse_qs(parsed.fragment)
                    access_token = fragment.get('access_token', [None])[0]
                    if access_token:
                        return {"success": True, "access_token": access_token}
            
            # Leer respuesta para detectar errores
            text = await response.text()
            
            if "password is incorrect" in text.lower():
                return {"success": False, "error": "Contraseña incorrecta"}
            elif "account doesn't exist" in text.lower():
                return {"success": False, "error": "La cuenta no existe"}
            elif "recover" in text.lower():
                return {"success": False, "error": "Autenticación de 2 factores requerida"}
            elif "signed in too many times" in text.lower():
                return {"success": False, "error": "Demasiados intentos fallidos, cuenta temporalmente bloqueada"}
            else:
                return {"success": False, "error": "Error desconocido en autenticación"}

    except Exception as e:
        return {"success": False, "error": f"Error de conexión: {str(e)}"}

async def get_minecraft_profile(session, access_token):
    """Obtiene información del perfil de Minecraft"""
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
                
                return {
                    'profile': profile_data,
                    'name_change': name_change_data,
                    'entitlements': entitlements_data
                }
            elif response.status == 404:
                return {"success": False, "error": "Cuenta sin Minecraft"}
            else:
                return {"success": False, "error": f"Error API Minecraft: {response.status}"}
                
    except Exception as e:
        return {"success": False, "error": f"Error obteniendo perfil: {str(e)}"}

async def verify_microsoft_account(email, password):
    """
    Verifica una cuenta de Microsoft con manejo mejorado de errores
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

        # Configurar sesión HTTP
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(verify_ssl=False)
        
        async with aiohttp.ClientSession(
            connector=connector, 
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        ) as session:
            
            # Paso 1: Login con Microsoft
            login_result = await microsoft_login(session, email, password)
            
            if not login_result["success"]:
                return login_result

            access_token = login_result["access_token"]

            # Paso 2: Obtener información de Minecraft
            profile_result = await get_minecraft_profile(session, access_token)
            
            if isinstance(profile_result, dict) and "success" in profile_result and not profile_result["success"]:
                # Cuenta válida pero sin Minecraft
                return {
                    "success": True,
                    "email": email,
                    "password": password,
                    "has_minecraft": False,
                    "message": "✅ Cuenta Microsoft válida - Sin Minecraft",
                    "microsoft_token": access_token
                }

            # Cuenta con Minecraft - Procesar información
            profile_data = profile_result['profile']
            name_change_data = profile_result['name_change']
            entitlements_data = profile_result['entitlements']

            # Determinar tipo de cuenta
            account_type = "Microsoft Account"
            games_owned = []
            
            if entitlements_data and 'items' in entitlements_data:
                for item in entitlements_data['items']:
                    name = item.get('name', '')
                    if 'game_pass' in name:
                        if 'ultimate' in name:
                            account_type = "Xbox Game Pass Ultimate"
                        else:
                            account_type = "Xbox Game Pass"
                    elif 'minecraft' in name:
                        if 'bedrock' in name:
                            games_owned.append("Minecraft Bedrock")
                        elif 'legends' in name:
                            games_owned.append("Minecraft Legends")
                        elif 'dungeons' in name:
                            games_owned.append("Minecraft Dungeons")

            # Información de capas
            capes = []
            if 'capes' in profile_data:
                for cape in profile_data['capes']:
                    capes.append(cape.get('alias', 'Unknown'))

            # Información de cambio de nombre
            name_changeable = "No"
            if name_change_data:
                name_changeable = "Sí" if name_change_data.get('nameChangeAllowed', False) else "No"

            # Fecha de creación
            creation_date = "Desconocida"
            if name_change_data and 'createdAt' in name_change_data:
                try:
                    from datetime import datetime
                    created_at = name_change_data['createdAt']
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    creation_date = dt.strftime("%d/%m/%Y %H:%M")
                except:
                    creation_date = "Desconocida"

            return {
                "success": True,
                "email": email,
                "password": password,
                "has_minecraft": True,
                "message": "✅ Cuenta verificada exitosamente",
                "details": {
                    "username": profile_data.get('name', 'No disponible'),
                    "uuid": profile_data.get('id', 'No disponible'),
                    "account_type": account_type,
                    "capes": ", ".join(capes) if capes else "Ninguna",
                    "name_changeable": name_changeable,
                    "creation_date": creation_date,
                    "games_owned": ", ".join(games_owned) if games_owned else "Ninguno",
                    "access_token": access_token
                }
            }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "Tiempo de espera agotado. La verificación tomó demasiado tiempo."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error inesperado: {str(e)}"
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

# --- Comandos Mejorados ---

@bot.command(name='verifyaccount')
@commands.has_permissions(administrator=True)
async def verify_account(ctx, email: str, password: str):
    """Verifica una cuenta de Microsoft con mejor manejo de errores."""
    
    # Mensaje de procesamiento
    processing_msg = await ctx.send("🔍 **Verificando cuenta Microsoft...**\n⏳ Esto puede tomar 10-20 segundos")
    
    try:
        # Ejecutar verificación
        result = await verify_microsoft_account(email, password)
        
        # Eliminar mensaje de procesamiento
        await processing_msg.delete()
        
        if result["success"]:
            if result.get("has_minecraft", False):
                details = result["details"]
                
                # Embed para cuenta CON Minecraft
                embed = discord.Embed(
                    title="🎮 **CUENTA VERIFICADA - MINECRAFT DETECTADO**",
                    color=0x00ff00,
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(
                    name="📧 **Credenciales**",
                    value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                    inline=False
                )
                
                embed.add_field(
                    name="👤 **Información de Cuenta**",
                    value=f"**Usuario:** `{details['username']}`\n**UUID:** `{details['uuid']}`\n**Tipo:** {details['account_type']}",
                    inline=False
                )
                
                embed.add_field(
                    name="🎨 **Personalización**", 
                    value=f"**Capas:** {details['capes']}\n**Cambio nombre:** {details['name_changeable']}",
                    inline=True
                )
                
                embed.add_field(
                    name="📅 **Información Adicional**",
                    value=f"**Creación:** {details['creation_date']}\n**Juegos:** {details['games_owned']}",
                    inline=True
                )
                
                embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar")
                
            else:
                # Embed para cuenta SIN Minecraft
                embed = discord.Embed(
                    title="✅ **CUENTA VERIFICADA - SIN MINECRAFT**",
                    color=0xffff00,
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(
                    name="📧 **Credenciales**",
                    value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                    inline=False
                )
                
                embed.add_field(
                    name="💡 **Estado**",
                    value="Cuenta Microsoft válida pero no tiene Minecraft asociado",
                    inline=False
                )
                
                embed.set_footer(text="Reacciona con ✅ para añadir al inventario o ❌ para cancelar")
            
            # Enviar embed y añadir reacciones
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
            # Embed de ERROR
            embed = discord.Embed(
                title="❌ **ERROR EN VERIFICACIÓN**",
                color=0xff0000,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="📧 **Credenciales**",
                value=f"```\nEmail: {email}\nContraseña: {password}\n```",
                inline=False
            )
            
            embed.add_field(
                name="🚨 **Error Detectado**",
                value=f"**{result['error']}**",
                inline=False
            )
            
            embed.set_footer(text="Verifica las credenciales e intenta nuevamente")
            
            await ctx.send(embed=embed)
            
    except Exception as e:
        await processing_msg.delete()
        
        embed = discord.Embed(
            title="💥 **ERROR CRÍTICO**",
            description=f"Ocurrió un error inesperado: ```{str(e)}```",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@bot.command(name='addaccount')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """Añade una cuenta manualmente al inventario."""
    email_lower = email.lower()

    if email_lower in bot.registered_emails:
        embed = discord.Embed(
            title="❌ **Cuenta Duplicada**",
            description=f"La cuenta `{email}` ya existe en el inventario.",
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
        description=f"La cuenta ha sido añadida al inventario.",
        color=0x00ff00
    )
    embed.add_field(name="📧 Email", value=email, inline=True)
    embed.add_field(name="🔒 Contraseña", value=password, inline=True)
    embed.add_field(name="📊 Total", value=f"{len(bot.accounts_data['available'])} disponibles", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='test')
async def test_command(ctx):
    """Comando de prueba para verificar que el bot funciona."""
    embed = discord.Embed(
        title="🤖 **Bot Funcionando**",
        description="El bot está en línea y respondiendo correctamente.",
        color=0x0099ff
    )
    embed.add_field(name="📊 Cuentas Disponibles", value=len(bot.accounts_data['available']), inline=True)
    embed.add_field(name="🕒 Tiempo Activo", value="En línea", inline=True)
    
    await ctx.send(embed=embed)

# Manejo de reacciones
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
                    'added_date': datetime.now().isoformat(),
                    'added_by': str(user)
                }
                
                # Añadir detalles si tiene Minecraft
                if account_data.get("has_minecraft") and "details" in account_data:
                    new_account.update(account_data["details"])
                
                bot.accounts_data['available'].append(new_account)
                bot.registered_emails.add(email_lower)
                save_accounts()
                
                embed = discord.Embed(
                    title="✅ **Cuenta Añadida**",
                    description=f"La cuenta ha sido añadida al inventario.",
                    color=0x00ff00
                )
                embed.add_field(name="📧 Email", value=account_data["email"], inline=True)
                embed.add_field(name="📊 Total", value=f"{len(bot.accounts_data['available'])} disponibles", inline=True)
                
                await reaction.message.reply(embed=embed)
                
            else:
                await reaction.message.reply("❌ Esta cuenta ya existe en el inventario.")
            
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()
        
        elif str(reaction.emoji) == "❌" and user != bot.user:
            await reaction.message.reply("❌ Cuenta descartada.")
            del bot.temp_verified_accounts[reaction.message.id]
            await reaction.message.clear_reactions()

# --- Eventos del Bot ---
@bot.event
async def on_ready():
    print(f'🤖 Bot conectado como {bot.user}')
    load_accounts()
    
    if not distribute_account.is_running():
        distribute_account.start()

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
