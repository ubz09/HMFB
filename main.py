# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask
# ¡¡IMPORTANTE!! requests es necesario para el checker
import requests 

# --- Configuración Inicial ---
TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
DISTRIBUTION_INTERVAL_MINUTES = 30.0

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
registered_emails = set()

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
                # Recorrer ambas listas para cargar los emails
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

# --------------------------------------------------------------------------------------------------
## 🚀 Función Central de Chequeo y Extracción (Checker)
# --------------------------------------------------------------------------------------------------

def check_and_extract_ms_account(email: str, password: str):
    """
    Simula la autenticación de Microsoft para validar credenciales y extraer el perfil.
    
    ⚠️ IMPORTANTE: DEBES REEMPLAZAR EL CONTENIDO DE ESTA FUNCIÓN con la lógica de 
    peticiones HTTP de tu "codigochecker.txt".
    
    Retorna: (True, dict_info) si es válido, (False, str_error) si falla.
    """
    
    # ----------------------------------------------------------------------------------
    # !!! ZONA A COMPLETAR CON TU LÓGICA ESPECÍFICA DE PETICIONES DE AUTENTICACIÓN !!!
    # ----------------------------------------------------------------------------------
    
    session = requests.Session()
    
    try:
        # Aquí iría tu código de `codigochecker.txt` para autenticación de MS.
        
        # --- SIMULACIÓN DE RESULTADO ---
        # Por ahora, simulamos que siempre falla para que no se use sin implementar la lógica.
        
        # Si la lógica de tu checker confirma que la cuenta es válida:
        if False: # Cambiar esta línea a `if True:` o a la lógica de éxito real.
            extracted_info = {
                'username': email.split('@')[0], 
                'gmail': email,                  
                'password': password,            
                'status_check': 'Verified',      
                'extracted_gamertag': 'Gamertag-Extraído' 
            }
            return True, extracted_info 
        else:
            # Si el checker encuentra un error de credenciales o la simulación falla:
             return False, "Credenciales inválidas o la lógica de chequeo no ha sido implementada/falló."
            
    except requests.exceptions.RequestException as e:
        # Error de conexión, timeout, etc.
        return False, f"Error de conexión HTTP durante el chequeo: {e}"
    except Exception as e:
        # Error interno, ej. parseo de respuesta
        return False, f"Error interno en el checker: {e}"
        
    # ----------------------------------------------------------------------------------
    # FIN DE ZONA A COMPLETAR
    # ----------------------------------------------------------------------------------

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
        # Si falla el envío, devolver la cuenta
        accounts_data['available'].insert(0, account_to_distribute)

# ---------------------------------------------------------------------------------
# 🚀 CORRECCIÓN DEL SYNTAXERROR AQUÍ
# ---------------------------------------------------------------------------------
@bot.event
async def on_reaction_add(reaction, user): # <<--- ESTA LÍNEA FUE CORREGIDA (Línea ~213)
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
# ---------------------------------------------------------------------------------

# --- Comandos ---

@bot.command(name='addaccount', help='Añade una cuenta de Microsoft (Email y Password). Formato: !addaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def add_account(ctx, email: str, password: str):
    """
    Añade una cuenta al inventario de forma manual.
    """
    email_lower = email.lower()

    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta con correo **{email}** ya existe en el inventario.")
        return

    await ctx.send("✅ Recibida la información.")

    new_account = {'username':email,'gmail':email,'password':password}
    accounts_data['available'].append(new_account)
    registered_emails.add(email_lower)
    save_accounts()
    update_log(new_account,"ADDED_MANUALLY")

    # Enviar confirmación con Embed
    embed = discord.Embed(
        title="✅ Cuenta Añadida",
        description="La cuenta ha sido añadida manualmente al inventario.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📧 Correo (Microsoft)", value=email)
    embed.add_field(name="Inventario Total", value=f"{len(accounts_data['available'])} disponibles")
    await ctx.send(embed=embed)

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


@bot.command(name='checkaccount', help='Valida credenciales MS, extrae datos y añade la cuenta automáticamente. Formato: !checkaccount <correo> <contraseña>')
@commands.has_permissions(administrator=True)
async def check_account(ctx, email: str, password: str):
    """
    Usa la lógica del checker para validar, extraer datos del perfil 
    y añadir la cuenta al inventario si es válida y no es duplicada.
    """
    email_lower = email.lower()

    if email_lower in registered_emails:
        await ctx.send(f"❌ La cuenta **{email}** ya existe en el inventario (duplicada).")
        return

    await ctx.send(f"⏳ Iniciando chequeo y validación de la cuenta **{email}**...")

    # Llamar a la función del checker de forma asíncrona
    is_valid, result = await bot.loop.run_in_executor(None, check_and_extract_ms_account, email, password)

    if is_valid:
        # La cuenta es válida, 'result' contiene el diccionario de información
        new_account = result
        
        # Añadir al inventario
        accounts_data['available'].append(new_account)
        registered_emails.add(email_lower)
        save_accounts()
        update_log(new_account,"VERIFIED_AND_ADDED")

        embed = discord.Embed(
            title="✅ Cuenta Verificada y Añadida",
            description="La cuenta es válida, se extrajo la información y se añadió al inventario.",
            color=discord.Color.green()
        )
        embed.add_field(name="📧 Correo (MS)", value=email)
        embed.add_field(name="🔒 Contraseña", value=password)
        embed.add_field(name="Estado", value=new_account.get('status_check', 'Verified'))
        embed.add_field(name="Gamertag/Info Extraída", value=new_account.get('extracted_gamertag', 'N/A'), inline=False)
        embed.set_footer(text=f"Inventario Total: {len(accounts_data['available'])} disponibles")
        await ctx.send(embed=embed)
        
    else:
        # La cuenta no es válida, 'result' contiene el mensaje de error
        update_log({'gmail':email, 'password':password}, f"FAILED_CHECK: {result}")
        
        embed = discord.Embed(
            title="❌ Fallo en la Verificación",
            description="Las credenciales no son válidas o el proceso de chequeo falló.",
            color=discord.Color.red()
        )
        embed.add_field(name="📧 Correo", value=email)
        embed.add_field(name="Razón del Fallo", value=result, inline=False)
        await ctx.send(embed=embed)


@check_account.error
async def check_account_error(ctx, error):
    """Maneja errores específicos del nuevo comando checkaccount."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorrecto: `!checkaccount <correo_completo> <contraseña>`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Permiso denegado. Solo administradores pueden usar este comando.")
    else:
        print(f"Error inesperado en check_account: {error}")
        await ctx.send("❌ Error inesperado al chequear la cuenta. Revisa la consola para más detalles.")


@bot.command(name='importaccounts', help='Importa varias cuentas desde archivo import_accounts.txt con formato: correo:contraseña')
@commands.has_permissions(administrator=True)
async def import_accounts(ctx):
    """
    Importa cuentas desde un archivo de texto.
    """
    file_path = "import_accounts.txt"
    if not os.path.exists(file_path):
        await ctx.send(f"❌ No se encontró el archivo {file_path}. Asegúrate de crearlo con formato `correo:contraseña` por línea.")
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
            update_log(new_account,"ADDED_VIA_IMPORT")
            success_count += 1

        except Exception as e:
            remaining_lines.append(line) 
            print(f"Error procesando línea en import: {line}. Error: {e}")
            fail_count += 1

    save_accounts()

    if remaining_lines:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(remaining_lines) + '\n')
        await ctx.send(f"⚠️ **{fail_count}** líneas con formato incorrecto. Quedan en `{file_path}` para corrección.")
    else:
        remove_import_file(file_path)
    
    await ctx.send(
        f"✅ Importadas **{success_count}** cuentas correctamente.\n"
        f"🔄 Duplicadas (ya en inventario): **{duplicate_count}** (omitidas).\n"
        f"❌ Fallidas (formato incorrecto): **{fail_count}**."
    )


# --- Keep Alive y Ejecución Final (Necesario para Railway) ---

app = Flask('')
@app.route('/')
def home():
    """Ruta simple para mantener el bot activo en entornos como Railway."""
    return "Bot is running and ready!"

def run():
    """Ejecuta la aplicación Flask."""
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    """Inicia el thread para mantener la aplicación web activa."""
    t = Thread(target=run)
    t.start()

# --- Ejecución Final ---
if __name__ == '__main__':
    keep_alive()
    try:
        if not TOKEN:
            print("!!! ERROR: La variable de entorno DISCORD_TOKEN no está configurada. !!!")
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("*** ERROR: Token de Discord inválido ***")
    except Exception as e:
        print(f"*** ERROR FATAL: {e} ***")
