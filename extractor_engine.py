import asyncio
import os
import re
import time
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright

import config_fc as config

def get_installed_extensions(user_data_dir: str):
    """Mencari path ekstensi uBlock Origin / adblock yang terpasang di profil Chrome."""
    extensions_base = os.path.join(user_data_dir, "Default", "Extensions")
    valid_paths = []

    if not os.path.exists(extensions_base):
        return valid_paths

    for ext_id in os.listdir(extensions_base):
        ext_folder = os.path.join(extensions_base, ext_id)
        if os.path.isdir(ext_folder):
            try:
                versions = [v for v in os.listdir(ext_folder) if os.path.isdir(os.path.join(ext_folder, v))]
                if versions:
                    versions.sort()
                    target_version_path = os.path.join(ext_folder, versions[-1])
                    valid_paths.append(target_version_path)
            except Exception:
                pass

    return valid_paths

class FilecryptExtractorEngine:
    def __init__(self, container_url: str, output_folder: str, logger_func, container_password: str = ""):
        self.container_url = container_url.strip()
        self.output_folder = os.path.abspath(output_folder)
        os.makedirs(self.output_folder, exist_ok=True)
        
        self.container_password = container_password.strip()
        self.log = logger_func
        self.extracted_items = []  # Menyimpan dict: {"name": ..., "size": ..., "url": ...}
        self.container_title = "filecrypt_links"
        self._is_cancelled = False
        self.browser_context = None

    def cancel(self):
        """Memicu pembatalan dari antarmuka GUI."""
        self._is_cancelled = True
        self.log("[USER] Menerima sinyal pembatalan...")

    def _clean_filename(self, text: str) -> str:
        clean = re.sub(r'[\\/*?:"<>|]', "", text)
        clean = re.sub(r'\s+', " ", clean).strip()
        return clean if clean else "filecrypt_links"

    def _is_filecrypt_domain(self, url: str) -> bool:
        url_lower = url.lower()
        return any(domain in url_lower for domain in config.FILECRYPT_DOMAINS)

    def _is_ad_domain(self, url: str) -> bool:
        url_lower = url.lower()
        return any(keyword in url_lower for keyword in config.AD_BLACKLIST_KEYWORDS)

    async def _handle_popup_page(self, popup_page):
        """Mendeteksi dan menutup pop-
        up tab iklan baru secara instan."""
        try:
            await asyncio.sleep(0.4)
            popup_url = popup_page.url.lower()

            # Jika ini adalah domain iklan atau bukan domain resmi dan bukan target host
            if self._is_ad_domain(popup_url) or popup_url == "about:blank":
                self.log(f"[ANTI-ADS] Menutup tab pop-up iklan: {popup_url[:55]}...")
                await popup_page.close()
            elif not self._is_filecrypt_domain(popup_url):
                # Kemungkinan pop-up ini adalah target link host asli (misal drive.google.com, mega.nz)
                # Biarkan sementara atau pantau jika dibutuhkan
                pass
        except Exception:
            pass

    async def _remove_fake_captcha_overlays(self, page):
        """Menghapus honeypot trap, iframe clickjacking, floating ad div, dan elemen overlay transparan."""
        try:
            await page.evaluate("""
                () => {
                    // 1. Hapus link honeypot jebakan bot Filecrypt (/Link/1 tersembunyi)
                    const honeypots = document.querySelectorAll('a[href*="/Link/1"], a[style*="left: -1000px"], a[style*="display: none"]');
                    honeypots.forEach(h => h.remove());

                    // 2. Hapus iframe iklan overlay (CloudPiko, popad, banner floating)
                    const adFrames = document.querySelectorAll('iframe[class*="container-ad"], iframe[id*="container-ad"], iframe[src*="ad"]');
                    adFrames.forEach(f => f.remove());
                    
                    // 3. Hilangkan box pop-up palsu atau hidden visit link
                    const fakeBoxes = document.querySelectorAll('div[class*="pl-ad"], div[class*="fiIItheadblock"]');
                    fakeBoxes.forEach(b => b.remove());

                    // 4. Hilangkan overlay klik transparan tak terlihat
                    const allDivs = document.querySelectorAll('div');
                    allDivs.forEach(d => {
                        const style = window.getComputedStyle(d);
                        if (style.position === 'fixed' && (parseInt(style.zIndex) > 9999 || style.zIndex === '2147483647') && style.opacity === '0') {
                            d.remove();
                        }
                    });
                }
            """)
        except Exception:
            pass

    async def _solve_security_check(self, page):
        """Menangani proteksi password dan verifikasi CutCaptcha/Cloudflare Filecrypt."""
        self.log("[SECURITY CHECK] Memeriksa verifikasi keamanan & proteksi password...")
        
        pow_container = page.locator(config.SELECTORS["pow_container"])
        pow_box = page.locator(config.SELECTORS["pow_box"])
        pwd_input = page.locator(config.SELECTORS["password_input"])
        turnstile_iframe = page.locator(config.SELECTORS["turnstile_iframe"])

        clicked_pow = False

        for second in range(180):  # Batas waktu tunggu toleransi hingga 3 menit
            if self._is_cancelled:
                return False

            # Bersihkan elemen overlay & honeypot
            await self._remove_fake_captcha_overlays(page)

            # 1. Cek tanda mutlak bahwa halaman kontainer sudah benar-benar terbuka:
            # - Ada tabel file dengan tombol download
            # - Form captcha (#pow-captcha) sudah TIDAK ada di halaman
            # - Form password (#p4assw0rt) sudah TIDAK ada
            has_table = await page.locator("table tr:has(a.button.download), table tr:has(.download)").count() > 0
            has_pow = await pow_container.count() > 0
            has_pwd = await pwd_input.count() > 0 and await pwd_input.first.is_visible()

            if has_table and not has_pow and not has_pwd:
                self.log("[SECURITY CHECK] Berhasil melewati verifikasi & tabel berkas telah terbuka!")
                return True

            # 2. Tangani Proteksi Password jika halaman meminta password
            if has_pwd:
                if self.container_password:
                    self.log(f"[PASSWORD] Memasukkan kata sandi kontainer otomatis...")
                    await pwd_input.first.fill(self.container_password)
                    await asyncio.sleep(0.3)
                    submit_btn = page.locator(config.SELECTORS["password_submit"]).first
                    if await submit_btn.count() > 0:
                        await submit_btn.click()
                    else:
                        await pwd_input.first.press("Enter")
                    await asyncio.sleep(2)
                    continue
                else:
                    if second % 15 == 0:
                        self.log("[PERINGATAN] Kontainer ini memerlukan kata sandi (Password)! Silakan isi kata sandi di jendela browser atau di kolom Password GUI.")

            # 3. Deteksi Cloudflare Turnstile
            if await turnstile_iframe.count() > 0 and await turnstile_iframe.first.is_visible():
                if second % 15 == 0:
                    self.log("[SECURITY CHECK] Terdeteksi Cloudflare Turnstile. Silakan centang kotak verifikasi pada browser jika bot belum melewatinya.")

            # 4. Tangani CutCaptcha Proof-of-Work (I am a human)
            if has_pow:
                try:
                    state = await pow_container.get_attribute("data-state")

                    # Jika masih idle dan belum diklik, lakukan simulasi klik natural ke kotak
                    if state == "idle" and await pow_box.is_visible() and not clicked_pow:
                        self.log("[SECURITY CHECK] Memicu verifikasi 'I am a human'...")
                        await pow_box.scroll_into_view_if_needed()
                        box = await pow_box.bounding_box()
                        if box:
                            # Gerakkan mouse ke checkbox di sebelah kiri kotak
                            target_x = box["x"] + 25
                            target_y = box["y"] + (box["height"] / 2)
                            await page.mouse.move(target_x, target_y, steps=8)
                            await asyncio.sleep(0.3)
                            await page.mouse.click(target_x, target_y)
                        else:
                            await pow_box.click(force=True)
                        clicked_pow = True
                        await asyncio.sleep(2)

                    # Jika sedang menghitung Proof-of-Work, bersabarlah (jangan tutup browser!)
                    elif state == "working":
                        if second % 5 == 0:
                            self.log(f"[SECURITY CHECK] Verifikasi PoW sedang diproses browser ('Verification in progress...'). Mohon tunggu...")

                    # Jika perhitungan selesai (Confirmed)
                    elif state == "done":
                        self.log("[SECURITY CHECK] PoW Terkonfirmasi (Confirmed)! Menunggu halaman kontainer termuat...")
                        await asyncio.sleep(2.5)
                        # Jika setelah 2.5 detik form belum auto-submit, bantu submit
                        if await pow_container.count() > 0:
                            try:
                                await page.evaluate("document.getElementById('cform')?.submit();")
                            except Exception:
                                pass
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=12000)
                        except Exception:
                            pass

                except Exception:
                    pass

            await asyncio.sleep(1)

        self.log("[SECURITY CHECK] Waktu tunggu verifikasi habis.")
        return False

    def _is_valid_final_host_url(self, url: str) -> bool:
        """Memvalidasi bahwa URL adalah link host unduhan riil (bukan Filecrypt, iklan, atau landing page kosong)."""
        if not url or url == "about:blank":
            return False
        if self._is_filecrypt_domain(url) or self._is_ad_domain(url):
            return False
        # Abaikan URL landing page host yang belum selesai redirect
        clean = url.strip().lower()
        if clean in (
            "https://datanodes.to/download", "http://datanodes.to/download",
            "https://datanodes.to", "http://datanodes.to",
            "https://rapidgator.net", "https://1fichier.com"
        ):
            return False
        return True

    async def _resolve_redirect(self, request_context, gateway_url: str) -> str:
        """Menelusuri URL pengalihan (redirect) secara cepat via HTTP request context (maks 1.5 detik)."""
        try:
            headers = {
                "Referer": self.container_url,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            }
            response = await request_context.get(gateway_url, headers=headers, max_redirects=5, timeout=1500)
            final_dest = response.url
            if self._is_valid_final_host_url(final_dest):
                return final_dest
        except Exception:
            pass
        return None

    async def _resolve_single_part(self, item: dict, is_retry: bool = False) -> str:
        """Menelusuri gateway link ke host asli. Jika stuck ditunggu maksimal 10 detik lalu tab pasti tertutup otomatis."""
        gateway_url = item["gateway"]
        
        # 1. Coba penelusuran cepat via HTTP request context (maks 1.5 detik)
        final_link = await self._resolve_redirect(self.browser_context.request, gateway_url)
        if final_link:
            return final_link

        # 2. Buka tab browser dengan pemantau timer non-blocking (garansi auto-close 10 detik)
        temp_page = None
        nav_task = None
        resolved_url = None
        start_time = time.time()
        max_duration = 10.0

        try:
            temp_page = await self.browser_context.new_page()
            await temp_page.set_extra_http_headers({"Referer": self.container_url})

            # Mulai navigasi di background task agar tidak memblokir event loop jika koneksi gateway hang
            async def _do_goto():
                try:
                    await temp_page.goto(gateway_url, wait_until="commit", timeout=9000)
                except Exception:
                    pass
                # Cek tombol konfirmasi perantara (Continue / Click here) jika ada
                try:
                    continue_btn = temp_page.locator("a:has-text('Continue'), button:has-text('Continue'), a#button, .btn-primary").first
                    if await continue_btn.count() > 0 and await continue_btn.is_visible():
                        await continue_btn.click(timeout=800)
                except Exception:
                    pass

            nav_task = asyncio.create_task(_do_goto())

            # Loop polling timer presisi (maksimal 10 detik dari start_time)
            while (time.time() - start_time) < max_duration:
                if self._is_cancelled:
                    break

                # Periksa URL tab sementara
                try:
                    c_url = temp_page.url
                    if self._is_valid_final_host_url(c_url):
                        resolved_url = c_url
                        break
                except Exception:
                    pass

                # Periksa jika link tujuan terbuka di tab/jendela pop-up lain
                for p in list(self.browser_context.pages):
                    if p != getattr(self, "main_page", None) and p != temp_page and not p.is_closed():
                        try:
                            p_url = p.url
                            if self._is_valid_final_host_url(p_url):
                                resolved_url = p_url
                                break
                        except Exception:
                            pass
                if resolved_url:
                    break

                await asyncio.sleep(0.3)

        except Exception:
            pass
        finally:
            # Batalkan nav_task jika masih berjalan
            if nav_task and not nav_task.done():
                nav_task.cancel()

            # Hentikan loading Chromium dan tutup tab seketika (100% garansi bebas tab menggantung)
            if temp_page and not temp_page.is_closed():
                try:
                    await temp_page.evaluate("window.stop();")
                except Exception:
                    pass
                try:
                    await temp_page.close(run_before_unload=False)
                except Exception:
                    pass

            # Bersihkan seluruh tab sekunder selain halaman utama
            for p in list(self.browser_context.pages):
                if p != getattr(self, "main_page", None) and not p.is_closed():
                    try:
                        await p.evaluate("window.stop();")
                    except Exception:
                        pass
                    try:
                        await p.close(run_before_unload=False)
                    except Exception:
                        pass

        return resolved_url

    async def run(self):
        async with async_playwright() as p:
            self.log("[SYSTEM] Memeriksa konfigurasi browser & ekstensi...")
            extension_paths = get_installed_extensions(config.USER_DATA_DIR)

            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ]

            if extension_paths:
                joined_extensions = ",".join(extension_paths)
                self.log(f"[EXTENSION] Mengaktifkan {len(extension_paths)} ekstensi adblock terpasang.")
                launch_args.extend([
                    f"--disable-extensions-except={joined_extensions}",
                    f"--load-extension={joined_extensions}"
                ])

            exec_path = config.CHROME_EXECUTABLE_PATH
            if exec_path:
                self.log(f"[SYSTEM] Menggunakan Chromium: {os.path.basename(exec_path)}")
            else:
                self.log("[SYSTEM] Menggunakan browser Playwright default.")

            try:
                self.browser_context = await p.chromium.launch_persistent_context(
                    user_data_dir=config.USER_DATA_DIR,
                    executable_path=exec_path,
                    headless=False,
                    args=launch_args,
                    viewport={"width": 1280, "height": 850}
                )
            except Exception as e:
                self.log(f"[ERROR BROWSER] Gagal membuka profil browser ({e}). Menggunakan profil sementara...")
                fallback_dir = os.path.join(config.BASE_DIR, "fc_chrome_profile")
                os.makedirs(fallback_dir, exist_ok=True)
                self.browser_context = await p.chromium.launch_persistent_context(
                    user_data_dir=fallback_dir,
                    executable_path=exec_path,
                    headless=False,
                    args=launch_args,
                    viewport={"width": 1280, "height": 850}
                )

            # Pasang Network-Level Ad Blocker langsung via Playwright Route
            async def ad_route_handler(route):
                req_url = route.request.url.lower()
                if self._is_ad_domain(req_url):
                    await route.abort()
                else:
                    await route.continue_()

            await self.browser_context.route("**/*", ad_route_handler)

            # Pasang Listener Penutup Pop-Up Iklan Liar
            self.browser_context.on("page", lambda new_p: asyncio.create_task(self._handle_popup_page(new_p)))

            # Hilangkan atribut navigator.webdriver dan netralkan window.open iklan liar
            await self.browser_context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                const _realOpen = window.open;
                window.open = function(url, name, specs) {
                    if (!url || url === 'about:blank') return null;
                    const u = url.toLowerCase();
                    if (u.includes('challenges.cloudflare.com') || u.includes('cutcaptcha.net')) {
                        return _realOpen.apply(window, arguments);
                    }
                    return null; // Blokir pop-up iklan liar
                };
            """)
            page = self.browser_context.pages[0] if self.browser_context.pages else await self.browser_context.new_page()
            self.main_page = page

            self.log(f"[NAVIGASI] Mengakses kontainer: {self.container_url}")
            try:
                await page.goto(self.container_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                self.log(f"[WARN] Kendala memuat halaman: {e}")

            # 1. Bersihkan iklan overlay & lewati verifikasi keamanan
            await self._remove_fake_captcha_overlays(page)
            solved = await self._solve_security_check(page)
            await asyncio.sleep(1.5)

            if self._is_cancelled:
                await self.browser_context.close()
                return None, [], "CANCELLED"

            if not solved:
                self.log("[GAGAL] Tidak dapat melewati verifikasi keamanan. Proses dihentikan.")
                await self.browser_context.close()
                return None, [], "FAILED"

            # 2. Mengambil Judul Kontainer Asli (misal: 'Bloodborne Game of the Year Edition...')
            detected_title = None

            # Di Filecrypt, judul berkas selalu berada di tag <h2> di dalam kontainer/window
            heading_elements = page.locator("div.container h2, div.window h2, div.content h2, h2")
            count_headings = await heading_elements.count()

            for h_idx in range(count_headings):
                el = heading_elements.nth(h_idx)
                if await el.is_visible():
                    txt = (await el.inner_text()).strip()
                    # Lewati logo 'Filecrypt' atau judul captcha 'Security Check'
                    if txt and txt.lower() != "filecrypt" and "security check" not in txt.lower():
                        detected_title = txt
                        break

            # Fallback ke tag <title> browser jika h2 belum terambil
            if not detected_title:
                try:
                    page_title = await page.title()
                    # page.title() di Filecrypt berformat: "Nama Kontainer - Filecrypt"
                    cleaned = re.sub(r'[-\s|]*filecrypt.*$', '', page_title, flags=re.IGNORECASE).strip()
                    if cleaned and "security check" not in cleaned.lower():
                        detected_title = cleaned
                except Exception:
                    pass

            if detected_title:
                self.container_title = self._clean_filename(detected_title)

            self.log(f"[INFO] Judul Kontainer Asli: '{self.container_title}'")

            # 3. Mendeteksi Jumlah Berkas Asli & Seluruh Baris Tabel Berkas (Anti-Terlewat)
            # 3. Baca Tabel dan Part Berkas yang Tersedia dengan Auto Force-Refresh
            items_to_extract = []
            max_table_attempts = 4

            for table_attempt in range(1, max_table_attempts + 1):
                # Ambil indikator jumlah part dari header container jika tersedia (contoh: "6/6 Online" atau "12/12 Online")
                expected_count = None
                try:
                    online_el = page.locator("em.online, .online").first
                    if await online_el.count() > 0:
                        info_text = (await online_el.inner_text()).strip()
                        m = re.search(r'(\d+)\s*/\s*(\d+)', info_text)
                        if m:
                            expected_count = int(m.group(2))
                        else:
                            m2 = re.search(r'(\d+)\s*Online', info_text, re.IGNORECASE)
                            if m2:
                                expected_count = int(m2.group(1))
                except Exception:
                    pass

                if expected_count and table_attempt == 1:
                    self.log(f"[INFO] Header kontainer mencantumkan total: {expected_count} part berkas online.")

                # Gulir layar bertahap untuk memicu pemuatan baris tabel jika tabel panjang
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 350);")
                    await asyncio.sleep(0.3)

                # Ekstraksi langsung via DOM JavaScript (100% akurat membaca setiap baris tr tanpa terlewat)
                raw_table_items = await page.evaluate("""
                    () => {
                        const results = [];
                        const rows = document.querySelectorAll('table tbody tr, table tr');
                        rows.forEach((r, idx) => {
                            const tds = r.querySelectorAll('td');
                            // Minimal baris berkas valid memiliki 3 kolom (status, nama, unduh)
                            if (tds.length >= 3) {
                                // 1. Ambil nama file
                                let name = '';
                                const titleTd = r.querySelector('td[title]');
                                if (titleTd && titleTd.getAttribute('title')) {
                                    name = titleTd.getAttribute('title').trim();
                                } else if (tds[1]) {
                                    name = tds[1].innerText.split('\\n')[0].trim();
                                }
                                if (!name) name = `Part_${results.length + 1}`;

                                // 2. Ambil ukuran file
                                let size = '';
                                if (tds.length >= 4 && tds[2]) {
                                    size = tds[2].innerText.trim();
                                }

                                // 3. Ambil link gateway dari kolom tombol terakhir
                                const lastTd = tds[tds.length - 1];
                                let href = null;
                                const linkTag = lastTd ? (lastTd.querySelector('a') || lastTd.querySelector('button')) : null;
                                if (linkTag) {
                                    href = linkTag.getAttribute('href');
                                    if (!href) {
                                        const oc = linkTag.getAttribute('onclick') || '';
                                        const match = oc.match(/['"](https?:\\/\\/[^'"]*\\/Link\\/[^'"]+|\\/?Link\\/[^'"]+)['"]/i);
                                        if (match) {
                                            href = match[1];
                                        } else {
                                            const m2 = oc.match(/open(?:Link)?\\s*\\(\\s*['"]([a-zA-Z0-9]{8,})['"]/i);
                                            if (m2) href = `/Link/${m2[1]}.html`;
                                        }
                                    }
                                }

                                // Fallback jika tombol ada di selector lain dalam baris (HANYA /Link/!)
                                if (!href) {
                                    const anyLink = r.querySelector('a[href*="/Link/"], a[href*="Link/"]');
                                    if (anyLink) href = anyLink.getAttribute('href');
                                }

                                // HANYA masukkan jika href mengandung /Link/ agar tidak salah ambil link host/logo iklan
                                if (href && (href.includes('/Link/') || href.includes('Link/'))) {
                                    results.push({ name, size, href });
                                }
                            }
                        });
                        return results;
                    }
                """)

                items_to_extract = []
                for item_data in raw_table_items:
                    full_gateway = urljoin(page.url, item_data["href"])
                    items_to_extract.append({
                        "name": item_data["name"],
                        "size": item_data["size"],
                        "gateway": full_gateway
                    })

                # Cek kelengkapan part terhadap expected_count
                if expected_count and len(items_to_extract) < expected_count:
                    if table_attempt < max_table_attempts:
                        self.log(f"[PERINGATAN] Terbaca {len(items_to_extract)} part dari total {expected_count} di header. Melakukan Force-Refresh ({table_attempt}/{max_table_attempts})...")
                        try:
                            await page.reload(wait_until="domcontentloaded", timeout=10000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                        continue
                    else:
                        self.log(f"[PERINGATAN] Mencapai batas refresh tabel ({len(items_to_extract)}/{expected_count} part). Melanjutkan ekstraksi...")
                        break
                else:
                    break

            self.log(f"[INFO] Berhasil membaca {len(items_to_extract)} part berkas dari tabel kontainer.")
            self.log(f"[INFO] Memulai penelusuran tujuan {len(items_to_extract)} part...")

            # 4. Telusuri Redirect Latar Belakang ke Host Asli (Putaran 1)
            for idx, item in enumerate(items_to_extract, 1):
                if self._is_cancelled:
                    break

                part_label = item["name"] + (f" ({item['size']})" if item["size"] else "")
                self.log(f"[ACTION] Menelusuri [{idx}/{len(items_to_extract)}] {part_label}...")

                final_link = await self._resolve_single_part(item)

                if final_link:
                    self.log(f"    -> [VALID HOST] {final_link}")
                    item["final_url"] = final_link
                else:
                    self.log(f"    -> [STUCK / TIMEOUT 10s] Tidak merespon dalam 10s -> Tab otomatis ditutup & masuk antrean cek ulang.")
                    item["final_url"] = None

                # Jeda adaptif untuk mencegah rate-limit Filecrypt
                sleep_delay = 1.0 if len(items_to_extract) > 6 else 0.5
                await asyncio.sleep(sleep_delay)

            # 5. VALIDASI KELENGKAPAN & AUTO-RETRY DENGAN HARD REFRESH
            pending_items = [it for it in items_to_extract if not it.get("final_url")]
            max_retries = 2

            for retry_round in range(1, max_retries + 1):
                if not pending_items or self._is_cancelled:
                    break

                self.log("=" * 60)
                self.log(f"[AUTO-RETRY] Ditemukan {len(pending_items)} dari {len(items_to_extract)} part belum lengkap.")
                self.log(f"[AUTO-RETRY] Menjalankan pengecekan ulang putaran ke-{retry_round}...")
                self.log("=" * 60)

                for p_item in list(pending_items):
                    if self._is_cancelled:
                        break

                    p_label = p_item["name"] + (f" ({p_item['size']})" if p_item["size"] else "")
                    self.log(f"[RETRY-{retry_round}] Mengecek ulang: {p_label} (tunggu maks 10 detik)...")

                    retry_link = await self._resolve_single_part(p_item, is_retry=True)
                    if retry_link:
                        self.log(f"    -> [RETRY BERHASIL] {retry_link}")
                        p_item["final_url"] = retry_link
                        pending_items.remove(p_item)
                    else:
                        self.log(f"    -> [STUCK] Masih belum merespon dalam 10 detik -> Tab ditutup.")
                        self.log(f"    -> [HARD REFRESH] Melakukan Hard Refresh halaman kontainer untuk memulihkan sesi...")
                        try:
                            await page.reload(wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(2.0)
                            
                            # Ekstrak kembali link gateway fresh dari baris tabel DOM yang baru di-refresh
                            fresh_href = await page.evaluate(f"""
                                () => {{
                                    const rows = document.querySelectorAll('table tbody tr, table tr');
                                    for (let r of rows) {{
                                        const tds = r.querySelectorAll('td');
                                        if (tds.length >= 3) {{
                                            const titleTd = r.querySelector('td[title]');
                                            let name = titleTd && titleTd.getAttribute('title') ? titleTd.getAttribute('title').trim() : (tds[1] ? tds[1].innerText.split('\\n')[0].trim() : '');
                                            if (name === "{p_item['name']}") {{
                                                const lastTd = tds[tds.length - 1];
                                                const linkTag = lastTd ? (lastTd.querySelector('a') || lastTd.querySelector('button')) : null;
                                                let href = linkTag ? linkTag.getAttribute('href') : null;
                                                if (!href && linkTag) {{
                                                    const oc = linkTag.getAttribute('onclick') || '';
                                                    const match = oc.match(/['"](https?:\\/\\/[^'"]*\\/Link\\/[^'"]+|\\/?Link\\/[^'"]+)['"]/i);
                                                    if (match) {{
                                                        href = match[1];
                                                    }} else {{
                                                        const m2 = oc.match(/open(?:Link)?\\s*\\(\\s*['"]([a-zA-Z0-9]{{8,}})['"]/i);
                                                        if (m2) href = `/Link/${{m2[1]}}.html`;
                                                    }}
                                                }}
                                                if (!href) {{
                                                    const anyLink = r.querySelector('a[href*="/Link/"], a[href*="Link/"]');
                                                    if (anyLink) href = anyLink.getAttribute('href');
                                                }}
                                                if (href && (href.includes('/Link/') || href.includes('Link/'))) {{
                                                    return href;
                                                }}
                                                return null;
                                            }}
                                        }}
                                    }}
                                    return null;
                                }}
                            """)
                            if fresh_href:
                                p_item["gateway"] = urljoin(page.url, fresh_href)
                                self.log(f"    -> [SESI DIPULIHKAN] Menelusuri ulang {p_label} dengan link fresh...")
                                retry_link2 = await self._resolve_single_part(p_item, is_retry=True)
                                if retry_link2:
                                    self.log(f"    -> [RETRY SUKSES SETELAH REFRESH] {retry_link2}")
                                    p_item["final_url"] = retry_link2
                                    pending_items.remove(p_item)
                        except Exception:
                            pass

                    await asyncio.sleep(1.0)

            # Rekapitulasi hasil
            valid_extracted_links = [it["final_url"] for it in items_to_extract if it.get("final_url")]
            failed_items = [it for it in items_to_extract if not it.get("final_url")]

            if failed_items:
                self.log(f"[CATATAN] Selesai dengan rincian: {len(valid_extracted_links)} berhasil, {len(failed_items)} part gagal diurai.")
            else:
                self.log(f"[SUKSES] Semua {len(valid_extracted_links)} part berhasil diekstrak 100% lengkap!")

            # 6. Menyimpan Hasil ke Berkas TXT Khusus (Sesuai Judul Kontainer Asli)
            saved_file_path = None
            if valid_extracted_links or failed_items:
                base_target = os.path.join(self.output_folder, f"{self.container_title}.txt")
                counter = 1
                saved_file_path = base_target
                while os.path.exists(saved_file_path):
                    saved_file_path = os.path.join(self.output_folder, f"{self.container_title}_{counter}.txt")
                    counter += 1

                with open(saved_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# Filecrypt Kontainer: {self.container_url}\n")
                    f.write(f"# Judul: {self.container_title}\n")
                    f.write(f"# Total Part di Kontainer: {len(items_to_extract)}\n")
                    f.write(f"# Berhasil Diekstrak: {len(valid_extracted_links)}\n")
                    if failed_items:
                        f.write(f"# Gagal / Perlu Cek Manual: {len(failed_items)}\n")
                    f.write("=" * 65 + "\n\n")
                    
                    # Bagian 1: Detail Part & Link (Transparan menampilkan status per part)
                    f.write("[DETAIL STATUS PART DAN LINK]\n")
                    for item in items_to_extract:
                        size_str = f" [{item['size']}]" if item.get("size") else ""
                        if item.get("final_url"):
                            f.write(f"{item['name']}{size_str} -> {item['final_url']}\n")
                        else:
                            f.write(f"{item['name']}{size_str} -> [GAGAL DIEKSTRAK / TIMEOUT] (Gateway: {item['gateway']})\n")
                    
                    # Bagian 2: Daftar Link Bersih (Hanya link valid yang siap disalin ke JDownloader/IDM)
                    f.write("\n[DAFTAR LINK BERSIH]\n")
                    for link in valid_extracted_links:
                        f.write(f"{link}\n")
                    f.flush()

                self.log(f"[SAVED] Berkas hasil tersimpan di: {saved_file_path}")

            status = "CANCELLED" if self._is_cancelled else ("SUCCESS" if valid_extracted_links else "FAILED")
            await asyncio.sleep(1)
            try:
                await self.browser_context.close()
            except Exception:
                pass

            return saved_file_path, valid_extracted_links, status


if __name__ == "__main__":
    import sys

    print("=" * 65)
    print("      FILECRYPT EXTRACTOR ENGINE (CLI MODE TEST)      ")
    print("=" * 65)

    cli_url = None
    cli_pwd = ""

    # 1. Cek argumen CLI: python extractor_engine.py <URL> [PASSWORD] atau --help
    if len(sys.argv) > 1:
        arg1 = sys.argv[1].strip()
        if arg1 in ("-h", "--help", "help"):
            print("Penggunaan CLI:")
            print("  python extractor_engine.py <URL_Filecrypt> [PASSWORD]")
            print("\nContoh:")
            print("  python extractor_engine.py https://filecrypt.cc/Container/14AA145468.html")
            print("  python extractor_engine.py https://filecrypt.cc/Container/14AA145468.html rahasia123")
            sys.exit(0)
        cli_url = arg1
        if len(sys.argv) > 2:
            cli_pwd = sys.argv[2].strip()
    else:
        # 2. Cek apakah ada link di file default fc_containers.txt
        if os.path.exists(config.DEFAULT_BATCH_INPUT):
            with open(config.DEFAULT_BATCH_INPUT, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip().startswith("http")]
                if lines:
                    cli_url = lines[0]
                    print(f"[*] Mengambil URL pertama dari '{os.path.basename(config.DEFAULT_BATCH_INPUT)}':\n    {cli_url}")

    # 3. Jika belum ada, minta input dari pengguna
    if not cli_url:
        print("\nMasukkan URL Kontainer Filecrypt yang ingin diekstrak:")
        try:
            cli_url = input("URL : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperasi dibatalkan.")
            sys.exit(0)

    if not cli_url or not cli_url.startswith("http"):
        print("\n[!] Error: Masukkan URL yang valid (diawali http:// atau https://)!")
        print("Contoh: python extractor_engine.py https://filecrypt.cc/Container/14AA145468.html")
        sys.exit(1)

    print(f"\n[+] Memulai penelusuran kontainer...")
    print(f"    Target   : {cli_url}")
    if cli_pwd:
        print(f"    Password : {cli_pwd}")
    print("-" * 65)

    def cli_logger(msg: str):
        print(msg)

    engine = FilecryptExtractorEngine(
        container_url=cli_url,
        output_folder=config.OUTPUT_DIR,
        logger_func=cli_logger,
        container_password=cli_pwd
    )

    if sys.platform == "win32" and sys.version_info < (3, 14):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    saved_file, links, status = asyncio.run(engine.run())

    print("\n" + "=" * 65)
    print(f"STATUS AKHIR       : {status}")
    print(f"TOTAL LINK DIDAPAT : {len(links)}")
    if saved_file:
        print(f"LOKASI FILE HASIL  : {saved_file}")
    print("=" * 65)

    if links:
        print("\n[DAFTAR TAUTAN HOST]")
        for i, l in enumerate(links, 1):
            print(f"  {i}. {l}")
    print()

