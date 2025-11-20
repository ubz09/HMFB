# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import json
import os
import re
import aiohttp
from datetime import datetime
from threading import Thread
from flask import Flask

TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
DISTRIBUTION_INTERVAL_MINUTES = 60.0

DATA_DIR = 'data'
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
LOGS_FILE = os.path.join(DATA_DIR, 'logs.txt')

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

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)

accounts_data = {'available': [], 'distributed': []}
registered_emails = set()

def load_accounts():
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
    except json.JSONDecodeError as e:
        print(f"Error al decodificar JSON: {e}")
        return False
    except Exception as e:
        print(f"Error cargando cuentas: {e}")
        return False

def save_accounts():
    try:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts_data, f, indent=4)
    except Exception as e:
        print(f"Error guardando cuentas: {e}")

def update_log(account_info, status):
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
    try:
        os.remove(file_path)
        print(f"Archivo de importación eliminado: {file_path}")
    except Exception as e:
        print(f"Error al eliminar archivo {file_path}: {e}")

def is_valid_email(email: str) -> bool:
    """Valida un email básico"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

async def get_minecraft_player_info(username: str):
    """Obtiene información del jugador de Minecraft (IGN y UUID)"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://api.mojang.com/users/profiles/minecraft/{username}') as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        'username': data['name'],
                        'uuid': data['id'],
                        'skin_url': f'https://skins.mcstats.com/head/{data["id"]}',
                        'body_front_url': f'https://skins.mcstats.com/body/front/{data["id"]}',
                        'body_back_url': f'https://skins.mcstats.com/body/back/{data["id"]}'
                    }
                return None
    except Exception as e:
        print(f"Error obteniendo info de Minecraft: {e}")
        return None

@bot.event
async def on_ready():
    print(f'🤖 Bot conectado como {bot.user}!')
    load_accounts()
    distribute_account.start()

@tasks.loop(minutes=DISTRIBUTION_INTERVAL_MINUTES)
async def distribute_account():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    if not channel or not accounts_data['available']:
        return

    account_to_distribute = accounts_data['available'].pop(0)

    required_keys = ['gmail', 'password']
    if not all(key in account_to_distribute for key in required_keys):
        accounts_data['available'].insert(0, account_to_distribute)
        return

    remaining_accounts = len(accounts_data['available'])
    
    minecraft_info = None
    if account_to_distribute.get('ign'):
        minecraft_info = await get_minecraft_player_info(account_to_distribute['ign'])
    
    embed = discord.Embed(
        title="✨ Cuenta Disponible ✨",
        description="Una nueva cuenta ha sido liberada del inventario. Indica su estado:",
        color=discord.Color.dark_green()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=f"`{account_to_distribute['gmail']}`", inline=False)
    embed.add_field(name="🔒 Contraseña", value=f"`{account_to_distribute['password']}`", inline=False)
    
    if minecraft_info:
        embed.add_field(name="🎮 IGN (In-Game Name)", value=f"`{minecraft_info['username']}`", inline=False)
        embed.add_field(name="🔑 UUID", value=f"`{minecraft_info['uuid']}`", inline=False)
        embed.set_thumbnail(url=minecraft_info['skin_url'])
    
    embed.add_field(name="📊 Inventario", value=f"{remaining_accounts} cuentas restantes", inline=False)
    embed.add_field(name="⚙️ Reacciona", value="✅ Usada | ❌ Error Credenciales | 🚨 Bloqueada", inline=False)
    embed.set_footer(text="Distribución automática")
    embed.timestamp = datetime.now()

    try:
        message = await channel.send(embed=embed)
        
        if minecraft_info:
            skin_embed = discord.Embed(color=discord.Color.dark_green())
            skin_embed.set_image(url=minecraft_info['body_front_url'])
            await channel.send(embed=skin_embed)
        
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
        
    except discord.Forbidden:
        print(f"Error: Sin permisos para enviar mensaje o agregar reacciones al canal {CHANNEL_ID}")
        accounts_data['available'].insert(0, account_to_distribute)
    except Exception as e:
        print(f"Error distribuyendo cuenta: {e}")
        accounts_data['available'].insert(0, account_to_distribute)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    valid_emojis = {"✅", "❌", "🚨"}

    if reaction.message.channel.id != CHANNEL_ID or str(reaction.emoji) not in valid_emojis:
        return

    message_id = reaction.message.id
    reacted_emoji = str(reaction.emoji)
    user_id = user.id

    account = next((acc for acc in accounts_data['distributed'] if acc.get('message_id') == message_id), None)
    
    if account is None:
        return
    
    if user_id in account['reactions']['users']:
        try:
            await reaction.remove(user)
        except discord.Forbidden:
            pass
        return

    account['reactions']['users'].append(user_id)
    account['reactions'][reacted_emoji] += 1
    save_accounts()

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña> [ign_minecraft]')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str, ign: str = None):
    email_lower = email.lower()
    
    if not is_valid_email(email):
        await ctx.send(f"❌ El email **{email}** no tiene un formato válido.")
        return

    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta con correo **{email}** ya existe en el inventario.")
        return

    await ctx.send("✅ Recibida la información.")
    new_account = {'username':email,'gmail':email,'password':password}
    
    if ign:
        new_account['ign'] = ign
    
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower)
    save_accounts()
    update_log(new_account,"ADDED")

    minecraft_info = None
    if ign:
        minecraft_info = await get_minecraft_player_info(ign)

    embed = discord.Embed(
        title="✅ Cuenta Añadida",
        description="La cuenta ha sido añadida al inventario y está lista para ser distribuida.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=f"`{email}`", inline=False)
    embed.add_field(name="🔒 Contraseña", value=f"`{password}`", inline=False)
    
    if minecraft_info:
        embed.add_field(name="🎮 IGN (In-Game Name)", value=f"`{minecraft_info['username']}`", inline=False)
        embed.add_field(name="🔑 UUID", value=f"`{minecraft_info['uuid']}`", inline=False)
        embed.set_thumbnail(url=minecraft_info['skin_url'])
    elif ign:
        embed.add_field(name="🎮 IGN (In-Game Name)", value=f"`{ign}`", inline=False)
        embed.add_field(name="⚠️ Nota", value="No se pudo obtener la información de Minecraft", inline=False)
    
    embed.add_field(name="📊 Inventario Total", value=f"{len(accounts_data['available'])} disponibles", inline=False)
    embed.set_footer(text="Cuenta registrada")
    embed.timestamp = datetime.now()
    await ctx.send(embed=embed)
    
    # Enviar embed con la skin si está disponible
    if minecraft_info:
        skin_embed = discord.Embed(color=discord.Color.blue())
        skin_embed.set_image(url=minecraft_info['body_front_url'])
        await ctx.send(embed=skin_embed)

@bot.command(name='importaccounts', help='Importa varias cuentas desde archivo import_accounts.txt con formato: correo:contraseña[:ign_minecraft]')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        await ctx.send(f"❌ No se encontró el archivo {file_path}.")
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
        if not stripped_line:
            continue

        # Aceptar formato: email:password o email:password:ign
        parts = stripped_line.split(":")
        if len(parts) < 2 or len(parts) > 3: 
            remaining_lines.append(line)
            fail_count += 1
            continue

        try:
            email = parts[0].strip()
            password = parts[1].strip()
            ign = parts[2].strip() if len(parts) == 3 else None
            
            email_lower = email.lower()

            if email_lower in registered_emails:
                duplicate_count += 1
                continue
            
            new_account = {'username':email,'gmail':email,'password':password}
            if ign:
                new_account['ign'] = ign
            
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
        await ctx.send(f"⚠️ **{fail_count}** líneas con formato incorrecto. Quedan en `{file_path}`.")
    else:
        remove_import_file(file_path)
    
    await ctx.send(
        f"✅ Importadas **{success_count}** cuentas.\n"
        f"🔄 Duplicadas: **{duplicate_count}**.\n"
        f"❌ Fallidas: **{fail_count}**."
    )

@add_account.error
async def add_account_error(ctx,error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorrecto: `!addaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado.")
    else:
        print(f"Error inesperado en add_account: {error}")
        await ctx.send("❌ Error al añadir la cuenta.")

app = Flask('')
@app.route('/')
def home():
    return "Bot is running and ready!"

def run():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        print(f"Error en Flask: {e}")

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.daemon = True
    t.start()

if __name__ == '__main__':
    keep_alive()
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("*** ERROR: Token de Discord inválido ***")
    except Exception as e:
        print(f"*** ERROR FATAL: {e} ***")
