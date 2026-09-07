#!/bin/bash
# Le dipendenze del fantabot su PythonAnywhere, e la prova che reggono.
#
# Si lancia UNA VOLTA, da una console Bash della dashboard:
#
#     bash ~/fanta/installa.sh
#
# Serve una console vera perche' l'API di PythonAnywhere sa scrivere file e
# ricaricare la web app, ma non sa eseguire comandi: le console che apre
# vanno aperte una volta dal browser prima di poterci parlare.
#
# ATTENZIONE A COSA CAMBIA PER GLI ALTRI PROGETTI. Questo comando porta
# python-telegram-bot alla 21.9 per tutto l'account. Un progetto che usa la 13
# — `from telegram import ParseMode`, che nella 21 non esiste piu' — smette di
# partire. Qui e' voluto: la web app passa al fantabot.

set -e

echo "== installo le dipendenze (python3.10, solo per il tuo utente)"
python3.10 -m pip install --user --upgrade \
    "python-telegram-bot[job-queue]==21.9" \
    "httpx>=0.27" \
    "beautifulsoup4>=4.12" \
    "lxml>=5.0" \
    "openpyxl>=3.1"

echo
echo "== controllo che si importi tutto quello che serve"
cd ~/fanta
PYTHONPATH=~/fanta/src python3.10 - <<'PY'
import telegram
print("python-telegram-bot", telegram.__version__)
import httpx, bs4, lxml, openpyxl  # noqa: F401
print("httpx, bs4, lxml, openpyxl: ok")

from fantabot.bot.web import application  # noqa: F401
print("fantabot: si importa")

from fantabot.db import connetti
c = connetti()
n = c.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
print(f"database: {n} giocatori")
PY

echo
echo "== dico a Telegram dove bussare"
PYTHONPATH=~/fanta/src python3.10 - <<'PY'
import os

from fantabot.bot.web import registra_webhook

dominio = os.environ.get("PA_DOMINIO", "")
if not dominio:
    # Il nome della web app e' il nome utente: e' cosi' per tutti gli account
    # gratuiti, e chiederlo sarebbe chiedere una cosa che si sa gia'.
    dominio = f"{os.environ.get('USER', '')}.pythonanywhere.com"
url = f"https://{dominio}/telegram/"
esito = registra_webhook(url)
print(url, "->", esito.get("description") or esito)
PY

echo
echo "== fatto."
echo "   Manca un clic solo: la scheda Web della dashboard, bottone verde"
echo "   Reload. Da quel momento risponde il fantabot."
