import os
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_chrome_executable() -> str:
    """Mendeteksi jalur eksekusi Chrome/Chromium secara otomatis dengan fallback."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    # 1. Cari versi Chromium ms-playwright yang terpasang di sistem pengguna
    if local_app_data:
        playwright_glob = os.path.join(local_app_data, "ms-playwright", "chromium-*", "chrome-win64", "chrome.exe")
        candidates = glob.glob(playwright_glob)
        if candidates:
            candidates.sort()
            return candidates[-1]

    # 2. Fallback ke Google Chrome standar sistem
    system_chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(system_chrome):
        return system_chrome

    system_chrome_x86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    if os.path.exists(system_chrome_x86):
        return system_chrome_x86

    return None

CHROME_EXECUTABLE_PATH = get_chrome_executable()

# Jalur Profil Pengguna (Default: profil Chrome for Testing jika ada, atau profil lokal folder)
_local_app_data = os.environ.get("LOCALAPPDATA", "")
_chrome_testing_dir = os.path.join(_local_app_data, "Google", "Chrome for Testing", "User Data") if _local_app_data else ""
if _chrome_testing_dir and os.path.exists(_chrome_testing_dir):
    USER_DATA_DIR = _chrome_testing_dir
else:
    USER_DATA_DIR = os.path.join(BASE_DIR, "fc_chrome_profile")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(BASE_DIR, "hasil_ekstrak")
DEFAULT_BATCH_INPUT = os.path.join(BASE_DIR, "fc_containers.txt")

# Domain internal resmi Filecrypt
FILECRYPT_DOMAINS = [
    "filecrypt.cc",
    "filecrypt.co",
    "filecrypt.to"
]

# Daftar kata kunci blacklist pop-up & redirect iklan liar
AD_BLACKLIST_KEYWORDS = [
    "traffic", "adnetwork", "adsterra", "popads", "propellerads",
    "exoclick", "clickadu", "onclick", "tsyndicate", "hilltopads",
    "ad-maven", "monetag", "yllix", "adcash", "zeroredirect",
    "track", "affiliate", "landing", "promo", "betting", "casino",
    "slot", "bonus", "dating", "adult", "loan", "insurance",
    "crypto-airdrop", "giveaway", "survey", "wheel", "prize",
    "chromewebstore", "extension", "adblockghost", "updater",
    "tipeoyfyyigxp.site", "syndication", "go.oclaserver.com",
    "doubleclick", "adnxs", "coinhive", "popcash"
]

SELECTORS = {
    "turnstile_iframe": "iframe[src*='challenges.cloudflare.com']",
    "turnstile_token": "input[name='cf-turnstile-response']",
    "container_title": "div.container h2, div.window h2, div.content h2, h2",
    "download_buttons": "table tr a.button.download, table tr .download, a.button.download:visible",
    "password_input": "#p4assw0rt, input[name='password']",
    "password_submit": "#cform button, #cform input[type='submit'], button:has-text('continue')",
    "pow_container": "#pow-captcha",
    "pow_box": ".pow-captcha__box"
}