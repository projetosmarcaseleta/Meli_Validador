@echo off
title Meli Validador - Servidor Web
echo Iniciando Meli Validador na porta 8765...
cd /d "%~dp0"
py -3.13 -m uvicorn agrupar.web:app --host 127.0.0.1 --port 8765 --reload
pause
