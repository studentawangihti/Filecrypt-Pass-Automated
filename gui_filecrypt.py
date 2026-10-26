import os
import sys
import time
import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

from extractor_engine import FilecryptExtractorEngine
import config_fc as config

class FilecryptBatchGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Filecrypt Universal Batch Extractor")
        self.root.geometry("860x820")
        self.root.minsize(780, 700)

        self.start_time = None
        self.is_running = False
        self.stop_requested = False
        self.current_engine = None

        self._ensure_default_files()
        self._build_ui()
        self._update_clock()

    def _ensure_default_files(self):
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        if not os.path.exists(config.DEFAULT_BATCH_INPUT):
            with open(config.DEFAULT_BATCH_INPUT, "w", encoding="utf-8") as f:
                f.write("")

    def _build_ui(self):
        # HEADER
        header_frame = tk.Frame(self.root, pady=8)
        header_frame.pack(fill=tk.X)
        tk.Label(header_frame, text="Filecrypt Universal Batch Extractor", font=("Helvetica", 15, "bold")).pack()
        tk.Label(
            header_frame,
            text="Ekstraksi batch otomatis dengan proteksi anti-iklan agresif & dukungan CutCaptcha PoW",
            fg="#555", font=("Helvetica", 9, "italic")
        ).pack()

        # STATUS BAR WAKTU & ANTREAN
        status_frame = tk.Frame(self.root, padx=20)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        self.lbl_clock = tk.Label(status_frame, text="Waktu: 00:00:00", font=("Helvetica", 9, "bold"), fg="#333")
        self.lbl_clock.pack(side=tk.LEFT)

        self.lbl_progress = tk.Label(status_frame, text="Antrean: Siap", font=("Helvetica", 9, "bold"), fg="#0275d8")
        self.lbl_progress.pack(side=tk.LEFT, padx=30)

        self.lbl_elapsed = tk.Label(status_frame, text="Total Waktu: 00:00", font=("Helvetica", 9, "bold"), fg="#d9534f")
        self.lbl_elapsed.pack(side=tk.RIGHT)

        # INPUT AREA
        input_frame = tk.LabelFrame(self.root, text=" 1. Input URL Kontainer Filecrypt & Password ", padx=12, pady=8)
        input_frame.pack(fill=tk.X, padx=20, pady=5)

        btn_bar = tk.Frame(input_frame)
        btn_bar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(btn_bar, text="📁 Buka File .txt Luar", command=self._load_custom_txt).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_bar, text="📄 Muat 'fc_containers.txt' Default", command=self._load_default_txt).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_bar, text="🧹 Bersihkan Input", command=self._clear_input).pack(side=tk.RIGHT)

        self.txt_input = scrolledtext.ScrolledText(input_frame, height=5, font=("Consolas", 10))
        self.txt_input.pack(fill=tk.X)

        # Password Input Frame (Opsional)
        pwd_bar = tk.Frame(input_frame, pady=5)
        pwd_bar.pack(fill=tk.X)
        tk.Label(pwd_bar, text="🔑 Password Kontainer (Opsional):", font=("Helvetica", 9)).pack(side=tk.LEFT, padx=(0, 8))
        self.ent_password = ttk.Entry(pwd_bar, width=35, show="*")
        self.ent_password.pack(side=tk.LEFT)
        self.show_pwd_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(pwd_bar, text="Tampilkan", variable=self.show_pwd_var, command=self._toggle_pwd_visibility).pack(side=tk.LEFT, padx=8)

        # TOMBOL AKSI
        action_bar = tk.Frame(self.root)
        action_bar.pack(pady=6)

        self.btn_start = tk.Button(
            action_bar, text="🚀 Mulai Ekstrak Batch", font=("Helvetica", 10, "bold"),
            bg="#0275d8", fg="white", padx=16, pady=4, relief="groove", cursor="hand2",
            command=self.start_batch
        )
        self.btn_start.pack(side=tk.LEFT, padx=10)

        self.btn_stop = tk.Button(
            action_bar, text="🛑 Batalkan / Stop", font=("Helvetica", 10, "bold"),
            bg="#d9534f", fg="white", padx=16, pady=4, relief="groove", cursor="hand2",
            state="disabled", command=self.stop_batch
        )
        self.btn_stop.pack(side=tk.LEFT, padx=10)

        self.btn_open_folder = tk.Button(
            action_bar, text="📂 Buka Folder Hasil", font=("Helvetica", 9),
            bg="#f0f0f0", fg="#333", padx=12, pady=4, relief="groove", cursor="hand2",
            command=self._open_output_folder
        )
        self.btn_open_folder.pack(side=tk.LEFT, padx=10)

        # TERMINAL LOG AREA
        log_frame = tk.LabelFrame(self.root, text=" 2. Terminal Log Proses ", padx=10, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        self.txt_log = scrolledtext.ScrolledText(
            log_frame, height=12, state='disabled', bg="#1e1e1e", fg="#00ff00",
            insertbackground="white", font=("Consolas", 9)
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # OUTPUT AREA
        output_frame = tk.LabelFrame(self.root, text=" 3. Ringkasan Hasil Ekstraksi ", padx=10, pady=8)
        output_frame.pack(fill=tk.X, padx=20, pady=(5, 10))

        out_btn_bar = tk.Frame(output_frame)
        out_btn_bar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(out_btn_bar, text="📋 Salin Semua Tautan Layar", command=self._copy_results).pack(side=tk.LEFT)
        tk.Label(
            out_btn_bar, text=f"Tersimpan di: {os.path.basename(config.OUTPUT_DIR)}/",
            font=("Helvetica", 8, "italic"), fg="#5cb85c"
        ).pack(side=tk.RIGHT)

        self.txt_output = scrolledtext.ScrolledText(output_frame, height=5, font=("Consolas", 9))
        self.txt_output.pack(fill=tk.X)

    def _toggle_pwd_visibility(self):
        if self.show_pwd_var.get():
            self.ent_password.config(show="")
        else:
            self.ent_password.config(show="*")

    def _open_output_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(config.OUTPUT_DIR)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", config.OUTPUT_DIR])
        except Exception as e:
            messagebox.showerror("Gagal", f"Tidak dapat membuka folder: {e}")

    def _load_default_txt(self):
        if os.path.exists(config.DEFAULT_BATCH_INPUT):
            with open(config.DEFAULT_BATCH_INPUT, "r", encoding="utf-8") as f:
                content = f.read()
            self.txt_input.delete("1.0", tk.END)
            self.txt_input.insert(tk.END, content)
            messagebox.showinfo("Sukses", f"Berhasil memuat isi dari:\n{config.DEFAULT_BATCH_INPUT}")

    def _load_custom_txt(self):
        filepath = filedialog.askopenfilename(
            title="Pilih File Teks Berisi Link Kontainer",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filepath:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.txt_input.delete("1.0", tk.END)
            self.txt_input.insert(tk.END, content)

    def _clear_input(self):
        self.txt_input.delete("1.0", tk.END)

    def _copy_results(self):
        text = self.txt_output.get("1.0", tk.END).strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("Sukses", "Tautan hasil berhasil disalin ke clipboard!")
        else:
            messagebox.showwarning("Kosong", "Belum ada link yang terekstrak.")

    def log_message(self, msg: str):
        now_str = time.strftime("[%H:%M:%S] ")
        # Pastikan tidak ada double timestamp jika engine sudah menyertakannya
        formatted = f"{now_str}{msg}" if not (len(msg) > 9 and msg[0] == "[" and msg[3] == ":" and msg[6] == ":") else msg
        def _append():
            self.txt_log.configure(state='normal')
            self.txt_log.insert(tk.END, f"{formatted}\n")
            self.txt_log.configure(state='disabled')
            self.txt_log.yview(tk.END)
        self.root.after(0, _append)

    def _update_clock(self):
        self.lbl_clock.config(text=f"Waktu: {time.strftime('%H:%M:%S')}")
        if self.is_running and self.start_time:
            elapsed = int(time.time() - self.start_time)
            m, s = divmod(elapsed, 60)
            self.lbl_elapsed.config(text=f"Total Waktu: {m:02d}:{s:02d}")
        self.root.after(1000, self._update_clock)

    def stop_batch(self):
        if self.is_running:
            self.stop_requested = True
            self.btn_stop.config(state="disabled", text="Menghentikan...")
            self.log_message("[USER] Mengirim sinyal pembatalan ke engine...")
            if self.current_engine:
                self.current_engine.cancel()

    def start_batch(self):
        raw_text = self.txt_input.get("1.0", tk.END)
        global_pwd = self.ent_password.get().strip()

        # Parsing banyak link kontainer sekaligus (Multi-line batch)
        # Mendukung format: URL saja, atau URL | Password
        batch_items = []
        for line in raw_text.splitlines():
            line_str = line.strip()
            if not line_str or ("http://" not in line_str and "https://" not in line_str):
                continue
            if "|" in line_str:
                parts = line_str.split("|", 1)
                u = parts[0].strip()
                p = parts[1].strip()
                batch_items.append((u, p if p else global_pwd))
            else:
                batch_items.append((line_str, global_pwd))

        if not batch_items:
            messagebox.showwarning("Input Kosong", "Masukkan minimal satu URL kontainer Filecrypt yang valid!")
            return

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal", text="🛑 Batalkan / Stop")

        self.txt_output.delete("1.0", tk.END)
        self.txt_log.configure(state='normal')
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.configure(state='disabled')

        self.start_time = time.time()
        self.is_running = True
        self.stop_requested = False
        self.lbl_elapsed.config(text="Total Waktu: 00:00")

        thread = threading.Thread(target=self._run_batch_thread, args=(batch_items,))
        thread.daemon = True
        thread.start()

    def _run_batch_thread(self, batch_items):
        total = len(batch_items)
        success_count = 0

        # Pastikan Windows Proactor Event Loop Policy digunakan (hanya untuk versi < 3.14)
        if sys.platform == "win32" and sys.version_info < (3, 14):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                pass

        for index, (target_url, pwd) in enumerate(batch_items, 1):
            if self.stop_requested:
                break

            self.root.after(0, lambda idx=index, tot=total: self.lbl_progress.config(
                text=f"Antrean: Memproses {idx}/{tot}", fg="#0275d8"
            ))

            self.log_message("=" * 65)
            self.log_message(f"[BATCH {index}/{total}] Memproses Kontainer:")
            self.log_message(f"  URL: {target_url}")
            if pwd:
                self.log_message(f"  Password: (Diterapkan)")
            self.log_message("=" * 65)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.current_engine = FilecryptExtractorEngine(
                container_url=target_url,
                output_folder=config.OUTPUT_DIR,
                logger_func=self.log_message,
                container_password=pwd
            )

            saved_file, links, status = None, [], "FAILED"
            try:
                saved_file, links, status = loop.run_until_complete(self.current_engine.run())
            except Exception as e:
                self.log_message(f"[ERROR BATCH ITEM] {e}")
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
                self.current_engine = None

            if links:
                success_count += 1
                file_label = os.path.basename(saved_file) if saved_file else target_url
                header_line = f"=== [{index}/{total}] {file_label} ({len(links)} Part) ===\n"
                links_text = "\n".join(links) + "\n\n"
                self.root.after(0, lambda h=header_line, lt=links_text: self.txt_output.insert(tk.END, h + lt))

            if self.stop_requested:
                break

            if index < total:
                time.sleep(2.0)

        self.root.after(0, lambda: self._on_batch_finished(success_count, total))

    def _on_batch_finished(self, success: int, total: int):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled", text="🛑 Batalkan / Stop")

        if self.stop_requested:
            self.lbl_progress.config(text=f"Dihentikan: {success}/{total} Selesai", fg="#d9534f")
            messagebox.showwarning("Dibatalkan", f"Proses batch dihentikan. Berhasil mengekstrak {success} dari {total} kontainer.")
        else:
            self.lbl_progress.config(text=f"Selesai: {success}/{total} Berhasil", fg="#5cb85c")
            elapsed = int(time.time() - self.start_time)
            m, s = divmod(elapsed, 60)
            messagebox.showinfo(
                "Batch Selesai",
                f"Selesai dalam {m}m {s}s!\n\n"
                f"• Berhasil: {success} dari {total} kontainer\n"
                f"• Lokasi Berkas: {config.OUTPUT_DIR}"
            )

if __name__ == "__main__":
    root = tk.Tk()
    app = FilecryptBatchGUI(root)
    root.mainloop()
