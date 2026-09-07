#!/bin/bash
# Il fantabot su PythonAnywhere: dipendenze, dati, webhook.
#
# Si lancia da una console Bash della dashboard:
#
#     bash ~/fanta/installa.sh
#
# Serve una console vera perche' l'API di PythonAnywhere sa scrivere file e
# ricaricare la web app, ma non sa eseguire comandi: le console che apre vanno
# aperte una volta dal browser prima di poterci parlare.
#
# E' RILANCIABILE. Ogni passo o e' gia' a posto o si rifa' senza danno, quindi
# se un pezzo fallisce — il proxy che risponde 503, di solito — si rilancia e
# basta, senza chiedersi a che punto era rimasto.
#
# ATTENZIONE A COSA CAMBIA PER GLI ALTRI PROGETTI. Porta python-telegram-bot
# alla 21.9 per tutto l'account. Un progetto che usa la 13 — `from telegram
# import ParseMode`, che nella 21 non esiste piu' — smette di partire.

set -e
cd ~/fanta

echo "== 1. dipendenze (python3.10, solo per il tuo utente)"
python3.10 -m pip install --user --upgrade --quiet \
    "python-telegram-bot[job-queue]==21.9" \
    "httpx>=0.27" \
    "beautifulsoup4>=4.12" \
    "lxml>=5.0" \
    "openpyxl>=3.1"
echo "   ok"

echo
echo "== 2. controllo che si importi tutto"
PYTHONPATH=~/fanta/src python3.10 - <<'PY'
import telegram

print("   python-telegram-bot", telegram.__version__)
import bs4, httpx, lxml, openpyxl  # noqa: F401

print("   httpx, bs4, lxml, openpyxl: ok")
from fantabot.bot.web import application  # noqa: F401

print("   fantabot: si importa")
PY

echo
echo "== 3. i dati arrivati da GitHub Actions"
PYTHONPATH=~/fanta/src python3.10 - <<'PY'
from fantabot.bot.web import assorbi_se_arrivato
from fantabot.db import connetti

conn = connetti()
if assorbi_se_arrivato(conn):
    print("   pacco assorbito")
else:
    print("   niente da assorbire (o era gia' dentro)")
for t in ("giocatori", "statistiche", "campo", "infortuni", "calendario", "coppie"):
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"   {t:<14}{n}")
PY

echo
echo "== 4. dico a Telegram dove bussare"
# Il webhook e' l'unico passo che esce su internet, quindi e' l'unico che il
# proxy puo' far fallire. Non deve fermare lo script: i primi tre passi sono
# gia' fatti e rifarli non serve.
set +e
PYTHONPATH=~/fanta/src python3.10 - <<'PY'
import os

from fantabot.bot.web import registra_webhook

dominio = f"{os.environ.get('USER', '')}.pythonanywhere.com"
url = f"https://{dominio}/telegram/"
esito = registra_webhook(url)
if esito.get("ok"):
    print(f"   {url} -> {esito.get('description', 'registrato')}")
else:
    print(f"   NON registrato: {esito.get('description')}")
    print("   E' il proxy di PythonAnywhere, non un divieto: rilancia lo script.")
    raise SystemExit(1)
PY
esito_webhook=$?
set -e

echo
if [ $esito_webhook -eq 0 ]; then
    echo "== fatto. Manca un clic: scheda Web -> bottone verde Reload."
    echo "   Da quel momento risponde il fantabot."
else
    echo "== quasi: i primi tre passi sono a posto, manca solo il webhook."
    echo "   Rilancia:  bash ~/fanta/installa.sh"
fi
