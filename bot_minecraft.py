import discord
from discord.ext import commands
import asyncio
import aiohttp
import re
import json
import time
import os
from urllib.parse import urlparse, parse_qs
import logging
from typing import Dict, List, Optional
from datetime import datetime

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_minecraft.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('MinecraftBot')

class MinecraftVerifier:
    def __init__(self):
        self.sFTTag_url = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"
    
    async def get_urlPost_sFTTag(self, session):
        """Obtiene tokens iniciales para autenticación"""
        try:
            async with session.get(self.sFTTag_url, timeout=30) as response:
                text = await response.text()
                
            # Buscar sFTTag
            sFTTag_match = re.search(r'value="([^"]+)"\s+name="PPFT"', text)
            if not sFTTag_match:
                return None, None
                
            sFTTag = sFTTag_match.group(1)
            
            # Buscar urlPost
            urlPost_match = re.search(r'urlPost:\'([^\']+)\'', text)
            if urlPost_match:
                urlPost = urlPost_match.group(1)
                return urlPost, sFTTag
                
        except Exception as e:
            logger.error(f"Error getting tokens: {e}")
            return None, None
    
    async def get_xbox_token(self, session, email, password, urlPost, sFTTag):
        """Autentica con Microsoft y obtiene token Xbox"""
        try:
            data = {
                'login': email,
                'loginfmt': email,
                'passwd': password,
                'PPFT': sFTTag
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.post(urlPost, data=data, headers=headers, allow_redirects=False) as response:
                # Verificar redirect con token
                if 'Location' in response.headers:
                    location = response.headers['Location']
                    if 'access_token' in location:
                        parsed = urlparse(location)
                        fragment = parse_qs(parsed.fragment)
                        token = fragment.get('access_token', [None])[0]
                        if token:
                            return token, "SUCCESS"
                
                # Seguir redirect manualmente
                if response.status in [301, 302, 303]:
                    redirect_url = response.headers.get('Location', '')
                    if redirect_url:
                        async with session.get(redirect_url, allow_redirects=True) as final_response:
                            final_url = str(final_response.url)
                            if 'access_token' in final_url:
                                parsed = urlparse(final_url)
                                fragment = parse_qs(parsed.fragment)
                                token = fragment.get('access_token', [None])[0]
                                if token:
                                    return token, "SUCCESS"
                
                # Verificar errores en el texto de respuesta
                response_text = await response.text()
                
                if any(value in response_text for value in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt"]):
                    return None, "2FA_REQUIRED"
                    
                elif any(value in response_text.lower() for value in ["password is incorrect", "invalid credentials"]):
                    return None, "INVALID_CREDENTIALS"
                    
                elif "tried to sign in too many times" in response_text.lower():
                    return None, "TOO_MANY_ATTEMPTS"
                    
        except asyncio.TimeoutError:
            return None, "TIMEOUT"
        except Exception as e:
            logger.error(f"Error in Xbox auth: {e}")
            return None, "AUTH_ERROR"
            
        return None, "AUTH_FAILED"
    
    async def get_minecraft_token(self, session, xbox_token):
        """Obtiene token de Minecraft"""
        try:
            # Paso 1: Autenticar con Xbox Live
            xbox_payload = {
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com", 
                    "RpsTicket": xbox_token
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT"
            }
            
            async with session.post(
                'https://user.auth.xboxlive.com/user/authenticate',
                json=xbox_payload,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status != 200:
                    return None
                    
                xbox_data = await response.json()
                xbox_token = xbox_data.get('Token')
                uhs = xbox_data['DisplayClaims']['xui'][0]['uhs']
            
            # Paso 2: Obtener token XSTS
            xsts_payload = {
                "Properties": {
                    "SandboxId": "RETAIL",
                    "UserTokens": [xbox_token]
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT"
            }
            
            async with session.post(
                'https://xsts.auth.xboxlive.com/xsts/authorize',
                json=xsts_payload,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status != 200:
                    return None
                    
                xsts_data = await response.json()
                xsts_token = xsts_data.get('Token')
            
            # Paso 3: Obtener token de Minecraft
            mc_payload = {
                'identityToken': f"XBL3.0 x={uhs};{xsts_token}"
            }
            
            async with session.post(
                'https://api.minecraftservices.com/authentication/login_with_xbox',
                json=mc_payload,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    mc_data = await response.json()
                    return mc_data.get('access_token')
                    
        except Exception as e:
            logger.error(f"Error getting Minecraft token: {e}")
            
        return None
    
    async def get_minecraft_profile(self, session, mc_token):
        """Obtiene el perfil de Minecraft"""
        try:
            headers = {
                'Authorization': f'Bearer {mc_token}',
                'Content-Type': 'application/json'
            }
            
            async with session.get(
                'https://api.minecraftservices.com/minecraft/profile',
                headers=headers
            ) as response:
                
                if response.status == 200:
                    profile_data = await response.json()
                    username = profile_data.get('name', 'N/A')
                    uuid = profile_data.get('id', 'N/A')
                    capes = [cape["alias"] for cape in profile_data.get("capes", [])]
                    
                    return {
                        'username': username,
                        'uuid': uuid,
                        'capes': ", ".join(capes) if capes else "Ninguna",
                        'success': True
                    }
                elif response.status == 404:
                    return {
                        'username': 'N/A',
                        'uuid': 'N/A', 
                        'capes': 'Ninguna',
                        'success': True
                    }
                    
        except Exception as e:
            logger.error(f"Error getting Minecraft profile: {e}")
            
        return {'success': False, 'error': 'Failed to get profile'}
    
    async def check_account_ownership(self, session, mc_token):
        """Verifica los productos de Minecraft"""
        try:
            headers = {'Authorization': f'Bearer {mc_token}'}
            
            async with session.get(
                'https://api.minecraftservices.com/entitlements/license',
                headers=headers
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    items = data.get("items", [])
                    
                    has_minecraft = any(
                        item.get("name") in ["game_minecraft", "product_minecraft"] 
                        for item in items
                    )
                    
                    if has_minecraft:
                        return "Minecraft Java Edition"
                    else:
                        # Verificar otros productos
                        other_products = []
                        if any('product_minecraft_bedrock' in item.get("name", "") for item in items):
                            other_products.append("Bedrock")
                        if any('product_legends' in item.get("name", "") for item in items):
                            other_products.append("Legends")
                        if any('product_dungeons' in item.get("name", "") for item in items):
                            other_products.append("Dungeons")
                            
                        if other_products:
                            return f"Otros: {', '.join(other_products)}"
                        else:
                            return "Correo Válido (Sin Minecraft)"
                            
        except Exception as e:
            logger.error(f"Error checking ownership: {e}")
            
        return "Error verificando productos"
    
    async def verify_account(self, email, password):
        """Verifica una cuenta completa de Minecraft"""
        logger.info(f"Verificando cuenta: {email}")
        
        async with aiohttp.ClientSession() as session:
            try:
                # Paso 1: Tokens iniciales
                urlPost, sFTTag = await self.get_urlPost_sFTTag(session)
                if not urlPost:
                    return {
                        "success": False, 
                        "email": email,
                        "error": "No se pudieron obtener tokens iniciales"
                    }
                
                # Paso 2: Autenticación Microsoft
                xbox_token, auth_status = await self.get_xbox_token(session, email, password, urlPost, sFTTag)
                if auth_status != "SUCCESS":
                    return {
                        "success": False,
                        "email": email, 
                        "error": auth_status
                    }
                
                # Paso 3: Token Minecraft
                mc_token = await self.get_minecraft_token(session, xbox_token)
                if not mc_token:
                    return {
                        "success": False,
                        "email": email,
                        "error": "No se pudo obtener token de Minecraft"
                    }
                
                # Paso 4: Perfil Minecraft
                profile = await self.get_minecraft_profile(session, mc_token)
                if not profile['success']:
                    return {
                        "success": False,
                        "email": email,
                        "error": profile.get('error', 'Error obteniendo perfil')
                    }
                
                # Paso 5: Verificar productos
                account_type = await self.check_account_ownership(session, mc_token)
                
                return {
                    "success": True,
                    "email": email,
                    "minecraft_profile": profile,
                    "account_type": account_type,
                    "verification_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
            except Exception as e:
                logger.error(f"Error in verify_account: {e}")
                return {
                    "success": False,
                    "email": email,
                    "error": f"Error inesperado: {str(e)}"
                }

class MinecraftBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.dm_messages = True
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
        self.verifier = MinecraftVerifier()
        self.user_attempts = {}  # Para limitar intentos por usuario
        self.verification_log = []  # Log de verificaciones
        
    async def on_ready(self):
        logger.info(f'🤖 Bot conectado como {self.user.name}')
        logger.info(f'📊 Conectado a {len(self.guilds)} servidores')
        await self.change_presence(activity=discord.Game(name="Verificando cuentas Minecraft | !help"))
    
    async def on_message(self, message):
        # Ignorar mensajes del bot mismo
        if message.author == self.user:
            return
        
        # Solo responder a DMs
        if isinstance(message.channel, discord.DMChannel):
            await self.handle_dm(message)
        
        await self.process_commands(message)
    
    async def handle_dm(self, message):
        """Maneja mensajes directos"""
        content = message.content.strip()
        
        # Ignorar comandos que empiecen con prefix
        if content.startswith('!'):
            return
        
        # Verificar formato de cuenta (email:password)
        if ':' not in content:
            embed = discord.Embed(
                title="❌ Formato Incorrecto",
                description="Por favor envía las cuentas en formato:\n`email:contraseña`",
                color=0xff0000
            )
            await message.reply(embed=embed)
            return
        
        # Limitar intentos por usuario
        user_id = message.author.id
        if user_id not in self.user_attempts:
            self.user_attempts[user_id] = {'count': 0, 'last_attempt': time.time()}
        
        user_data = self.user_attempts[user_id]
        
        # Resetear contador si pasó mucho tiempo
        if time.time() - user_data['last_attempt'] > 300:  # 5 minutos
            user_data['count'] = 0
        
        # Limitar a 5 verificaciones por 5 minutos
        if user_data['count'] >= 5:
            embed = discord.Embed(
                title="⏰ Límite Alcanzado",
                description="Has alcanzado el límite de 5 verificaciones cada 5 minutos.",
                color=0xffa500
            )
            await message.reply(embed=embed)
            return
        
        user_data['count'] += 1
        user_data['last_attempt'] = time.time()
        
        # Mostrar mensaje de procesamiento
        processing_embed = discord.Embed(
            title="🔍 Verificando Cuenta...",
            description="Por favor espera mientras verificamos la cuenta de Minecraft.",
            color=0x00ffff
        )
        processing_msg = await message.reply(embed=processing_embed)
        
        try:
            # Verificar la cuenta
            email, password = content.split(':', 1)
            result = await self.verifier.verify_account(email.strip(), password.strip())
            
            # Log de verificación
            self.verification_log.append({
                'user_id': user_id,
                'username': str(message.author),
                'email': email,
                'success': result['success'],
                'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # Guardar log cada 10 verificaciones
            if len(self.verification_log) >= 10:
                self.save_verification_log()
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()
            
            # Enviar resultado
            if result['success']:
                await self.send_success_embed(message, result)
            else:
                await self.send_error_embed(message, result)
                
        except Exception as e:
            logger.error(f"Error handling DM: {e}")
            await processing_msg.delete()
            
            error_embed = discord.Embed(
                title="❌ Error Interno",
                description="Ocurrió un error interno al procesar la cuenta.",
                color=0xff0000
            )
            await message.reply(embed=error_embed)
    
    async def send_success_embed(self, message, result):
        """Envía embed de éxito"""
        profile = result['minecraft_profile']
        
        embed = discord.Embed(
            title="✅ **CUENTA VERIFICADA**",
            description=f"La cuenta ha sido verificada exitosamente.",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="👤 Información de la Cuenta",
            value=f"**Email:** ||{result['email']}||\n**Tipo:** {result['account_type']}",
            inline=False
        )
        
        embed.add_field(
            name="🎮 Perfil de Minecraft",
            value=f"**Usuario:** `{profile['username']}`\n**UUID:** `{profile['uuid']}`\n**Capas:** {profile['capes']}",
            inline=False
        )
        
        embed.add_field(
            name="📊 Estadísticas de Verificación",
            value=f"**Verificado el:** {result['verification_time']}\n**Estado:** ✅ Válida",
            inline=False
        )
        
        # Agregar avatar de Minecraft si tiene usuario
        if profile['username'] != 'N/A':
            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{profile['username']}")
        
        embed.set_footer(text=f"Verificado por {self.user.name}", icon_url=self.user.avatar.url)
        
        await message.reply(embed=embed)
    
    async def send_error_embed(self, message, result):
        """Envía embed de error"""
        error_messages = {
            "INVALID_CREDENTIALS": "❌ **Credenciales Inválidas**\nEl email o contraseña son incorrectos.",
            "2FA_REQUIRED": "⚠️ **Autenticación de Dos Factores**\nLa cuenta requiere 2FA y no puede ser verificada automáticamente.",
            "TOO_MANY_ATTEMPTS": "🔒 **Demasiados Intentos**\nLa cuenta ha sido bloqueada temporalmente por muchos intentos fallidos.",
            "TIMEOUT": "⏰ **Timeout**\nLa verificación tardó demasiado tiempo. Intenta nuevamente.",
            "AUTH_FAILED": "❌ **Error de Autenticación**\nFalló la autenticación con Microsoft."
        }
        
        error_msg = error_messages.get(result['error'], f"❌ **Error:** {result['error']}")
        
        embed = discord.Embed(
            title="❌ **VERIFICACIÓN FALLIDA**",
            description=error_msg,
            color=0xff0000,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📧 Cuenta Verificada",
            value=f"**Email:** ||{result['email']}||",
            inline=False
        )
        
        embed.set_footer(text=f"Verificado por {self.user.name}", icon_url=self.user.avatar.url)
        
        await message.reply(embed=embed)
    
    def save_verification_log(self):
        """Guarda el log de verificaciones"""
        try:
            with open('verification_log.json', 'w', encoding='utf-8') as f:
                json.dump(self.verification_log, f, indent=2, ensure_ascii=False)
            self.verification_log.clear()
        except Exception as e:
            logger.error(f"Error saving log: {e}")

    # Comandos del bot
    @commands.command()
    async def help(self, ctx):
        """Muestra ayuda del bot"""
        embed = discord.Embed(
            title="🤖 Minecraft Account Verifier",
            description="Verifica cuentas de Minecraft automáticamente por DM.",
            color=0x00ffff
        )
        
        embed.add_field(
            name="📝 Cómo Usar",
            value="Envía un DM al bot con:\n`email:contraseña`\n\nEl bot verificará automáticamente la cuenta y mostrará los resultados.",
            inline=False
        )
        
        embed.add_field(
            name="⚡ Límites",
            value="• 5 verificaciones cada 5 minutos por usuario\n• Solo funciona por Mensajes Directos\n• Formato: email:contraseña",
            inline=False
        )
        
        embed.add_field(
            name="🔧 Comandos",
            value="`!help` - Muestra esta ayuda\n`!stats` - Estadísticas del bot",
            inline=False
        )
        
        embed.set_footer(text="Bot creado para verificación segura de cuentas Minecraft")
        
        await ctx.send(embed=embed)
    
    @commands.command()
    @commands.is_owner()
    async def stats(self, ctx):
        """Estadísticas del bot (Solo Owner)"""
        total_verifications = len(self.verification_log) + sum(1 for _ in self.verification_log)
        
        embed = discord.Embed(
            title="📊 Estadísticas del Bot",
            color=0x00ff00
        )
        
        embed.add_field(name="👥 Usuarios Únicos", value=len(self.user_attempts), inline=True)
        embed.add_field(name="🔍 Verificaciones Totales", value=total_verifications, inline=True)
        embed.add_field(name="🟢 Cuentas Válidas", value=sum(1 for log in self.verification_log if log['success']), inline=True)
        embed.add_field(name="📈 Servidores", value=len(self.guilds), inline=True)
        embed.add_field(name="⏰ Uptime", value=f"<t:{int(self.uptime.timestamp())}:R>", inline=True)
        
        await ctx.send(embed=embed)

# Configuración y ejecución
def load_config():
    """Carga la configuración del bot"""
    config = {
        "token": os.getenv("DISCORD_TOKEN"),
        "log_channel": os.getenv("LOG_CHANNEL_ID")
    }
    
    # Intentar cargar de archivo si no hay variables de entorno
    if not config["token"] and os.path.exists("config_bot.json"):
        with open("config_bot.json", "r") as f:
            file_config = json.load(f)
            config.update(file_config)
    
    return config

async def main():
    config = load_config()
    
    if not config["token"]:
        logger.error("❌ No se encontró el token del bot")
        logger.info("💡 Crea un archivo config_bot.json con tu token o usa la variable de entorno DISCORD_TOKEN")
        return
    
    bot = MinecraftBot()
    bot.uptime = datetime.now()
    
    try:
        await bot.start(config["token"])
    except KeyboardInterrupt:
        logger.info("Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
