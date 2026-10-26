@echo off
title Filecrypt Universal Batch Extractor
cd /d "%~dp0"
echo ========================================================
echo   MENJALANKAN FILECRYPT UNIVERSAL BATCH EXTRACTOR
echo ========================================================
echo Membuka antarmuka grafis (GUI)...
python gui_filecrypt.py
if errorlevel 1 (
    echo.
    echo [ERROR] Gagal menjalankan aplikasi. Pastikan Python sudah terpasang.
    pause
)
