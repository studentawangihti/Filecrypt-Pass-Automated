@echo off
title Setup & Instalasi Dependensi - Filecrypt Extractor
cd /d "%~dp0"
echo ========================================================
echo   INSTALASI DEPENDENSI FILECRYPT UNIVERSAL EXTRACTOR
echo ========================================================
echo.
echo [1/2] Menginstal pustaka Python (playwright, requests)...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Gagal menginstal pustaka Python. Pastikan pip dan Python terpasang di sistem PATH.
    pause
    exit /b 1
)

echo.
echo [2/2] Menginstal browser Chromium Playwright...
playwright install chromium
if errorlevel 1 (
    echo.
    echo [ERROR] Gagal menginstal browser Playwright.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo   SEMUA DEPENDENSI BERHASIL TERPASANG 100%!
echo   Silakan klik dua kali 'Jalankan_GUI.bat' untuk mulai.
echo ========================================================
pause
