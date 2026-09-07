"""Il bot dietro un webhook, per stare dove non si puo' restare accesi.

PERCHE' ESISTE. Il bot normalmente fa polling: un processo che resta acceso e
chiede a Telegram se c'e' posta. Su PythonAnywhere gratis non si puo' — non ci
sono always-on task — ma **una web app c'e'**, ed e' sempre servita. Allora si
gira la direzione: invece di essere il bot a chiedere, e' Telegram a bussare.

Le tre cose che rendono possibile la versione gratuita, e vanno lette insieme:

  · la whitelist di PythonAnywhere blocca le uscite, non le entrate. Telegram
    arriva qui senza problemi, e la sola uscita che serve — `api.telegram.org`,
    per rispondere — e' l'unica che la whitelist permette;
  · le web app **non consumano CPU-seconds**, mentre consoles e task si'. Il
    bot vive quindi nella sola parte del piano gratuito che non ha un
    contatore;
  · i dati li legge GitHub Actions, che internet ce l'ha tutto, e li spedisce
    qui gia' pronti (vedi `dati/sincronizza.py`).

COME SI SERVE UN'APP ASINCRONA DA UN WSGI SINCRONO. `Application` di
python-telegram-bot vuole un event loop suo e vuole tenerselo. Qui il loop
vive in un thread di servizio, avviato una volta sola, e ogni richiesta gli
passa l'aggiornamento e **torna subito 200** senza aspettare la risposta.
Aspettare sarebbe peggio in tutti e due i modi: Telegram considera fallita una
consegna lenta e la ripete — e una consegna ripetuta, qui dentro, vuol dire un
acquisto registrato due volte.

SICUREZZA. L'URL non basta a proteggere niente. Telegram rimanda a ogni
chiamata l'intestazione `X-Telegram-Bot-Api-Secret-Token`, e senza quella
giusta qui non si entra: chi indovina l'indirizzo trova un 403. Sopra c'e'
comunque `UTENTI_AMMESSI`, che decide di chi il bot esegue gli ordini.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

from telegram import Update

from ..config import DATI, STAGIONE_CORRENTE, impostazioni
from ..dati import andamento, sincronizza
from ..db import connetti
from .main import costruisci

log = logging.getLogger("fantabot.web")

# Dove GitHub Actions lascia il pacco. Si assorbe all'avvio del processo, che
# e' esattamente il momento in cui Actions ha appena chiesto il reload.
PACCO = DATI / "riferimento.sqlite3"
SEGNO = DATI / "riferimento.assorbito"

INTESTAZIONE_SEGRETO = "HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"


def assorbi_se_arrivato(conn, pacco: Path = PACCO, segno: Path = SEGNO) -> bool:
    """Se c'e' un pacco piu' recente dell'ultimo assorbito, lo assorbe.

    Il confronto e' sulle date e non su una cancellazione, perche' il file va
    tenuto: se un reload va storto, il pacco e' ancora li' e il reload dopo lo
    riprende. Cancellarlo dopo averlo usato vorrebbe dire che un errore a meta'
    lascia il bot senza dati **e** senza il modo di rifarli.
    """
    if not pacco.exists():
        return False
    if segno.exists() and segno.stat().st_mtime >= pacco.stat().st_mtime:
        return False
    esito = sincronizza.assorbi(conn, pacco)
    if not esito.riuscito:
        log.error("pacco non assorbito: %s", esito.errore)
        return False

    # LA FOTOGRAFIA SI SCATTA QUI, non dall'altra parte. `andamento` e' una
    # storia che si accumula giornata dopo giornata, e Actions riparte ogni
    # volta dal pacco: la sua storia sarebbe lunga una riga. Qui invece il
    # database e' sempre lo stesso, quindi appena arrivano statistiche nuove
    # se ne prende nota, ed e' cosi' che nasce il "cosa e' successo domenica"
    # che il cumulato da solo non racconta.
    giornata = conn.execute(
        "SELECT MAX(giornate) FROM statistiche WHERE stagione = ?",
        (STAGIONE_CORRENTE,),
    ).fetchone()[0]
    if giornata:
        quante = andamento.fotografa(conn, giornata)
        log.info("fotografata la giornata %s: %s righe", giornata, quante)

    segno.write_text(
        f"{esito.righe} righe: "
        + ", ".join(f"{t} {n}" for t, n in sorted(esito.tabelle.items())),
        encoding="utf-8",
    )
    log.info("assorbite %s righe da %s", esito.righe, pacco.name)
    return True


class Applicazione:
    """L'app WSGI. Si costruisce una volta per processo."""

    def __init__(self) -> None:
        self.segreto = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        conn = connetti()
        assorbi_se_arrivato(conn)
        # Niente lavoro periodico: da qui non si esce verso le fonti, e
        # provarci riempirebbe i log di timeout ogni sei ore.
        self.bot = costruisci(conn, aggiorna_da_solo=False)
        self.loop = asyncio.new_event_loop()
        self.pronto = threading.Event()
        threading.Thread(target=self._servi, daemon=True).start()
        self.pronto.wait(timeout=30)

    def _servi(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.bot.initialize())
        self.loop.call_soon(self.pronto.set)
        self.loop.run_forever()

    def _consegna(self, dati: bytes) -> None:
        aggiornamento = Update.de_json(json.loads(dati), self.bot.bot)
        asyncio.run_coroutine_threadsafe(
            self.bot.process_update(aggiornamento), self.loop
        )

    def __call__(self, environ, start_response):
        def rispondi(codice: str, corpo: bytes = b"") -> list[bytes]:
            start_response(
                codice,
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(corpo))),
                ],
            )
            return [corpo]

        if environ.get("REQUEST_METHOD") != "POST":
            # Aprire l'indirizzo col browser deve dire se il bot e' vivo, e
            # nient'altro: nessun nome, nessun numero, nessun token.
            return rispondi("200 OK", b"fantabot")

        if self.segreto and environ.get(INTESTAZIONE_SEGRETO) != self.segreto:
            log.warning("richiesta senza il segreto giusto")
            return rispondi("403 Forbidden")

        try:
            quanti = int(environ.get("CONTENT_LENGTH") or 0)
            self._consegna(environ["wsgi.input"].read(quanti))
        except Exception:
            # Un 500 fa ritentare Telegram, e ritentare qui vuol dire eseguire
            # due volte lo stesso comando. Meglio un errore nei log e un 200:
            # l'aggiornamento e' perso, non raddoppiato.
            log.exception("aggiornamento non processato")
        return rispondi("200 OK")


_applicazione: Applicazione | None = None


def application(environ, start_response):
    """Il punto d'ingresso che PythonAnywhere si aspetta nel file WSGI."""
    global _applicazione
    if _applicazione is None:
        _applicazione = Applicazione()
    return _applicazione(environ, start_response)


def registra_webhook(url: str, segreto: str = "", tentativi: int = 5) -> dict:
    """Dice a Telegram dove bussare. Si lancia una volta, da qualunque parte.

    RIPROVA, e non per pignoleria. Su PythonAnywhere gratis le richieste in
    uscita passano da un proxy condiviso che ogni tanto risponde 503 anche
    verso un indirizzo permesso: e' un intoppo di un momento, non un divieto.
    Un solo tentativo trasforma quel momento in "non funziona", e la
    differenza fra le due cose e' un pomeriggio.
    """
    import time

    import httpx

    cfg = impostazioni()
    dati = {
        "url": url,
        "secret_token": segreto or os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
        "drop_pending_updates": True,
        "allowed_updates": ["message", "callback_query"],
    }
    ultimo: Exception | None = None
    for tentativo in range(tentativi):
        try:
            risposta = httpx.post(
                f"https://api.telegram.org/bot{cfg.token_telegram}/setWebhook",
                json=dati,
                timeout=30,
            )
            return risposta.json()
        except httpx.HTTPError as e:
            ultimo = e
            attesa = 2 ** tentativo
            log.warning("setWebhook fallito (%s), riprovo fra %ss", e, attesa)
            time.sleep(attesa)
    return {
        "ok": False,
        "description": f"non ci sono riuscito in {tentativi} tentativi: {ultimo}",
    }
