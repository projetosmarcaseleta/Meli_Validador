@echo off
title Meli Validador - Servidor Local
echo Iniciando Meli Validador na porta 3002...
cd /d "%~dp0"
py -3.13 app.py
pause
