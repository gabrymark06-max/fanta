"""Parlare con Telegram da dietro un proxy che ogni tanto si distrae.

IL FATTO. Su PythonAnywhere gratis le richieste in uscita passano da un proxy
condiviso, e quel proxy ogni tanto risponde `503 Service Unavailable` anche
verso un indirizzo permesso — `api.telegram.org` e' nella loro whitelist. Non
e' un divieto: e' un intoppo di mezzo secondo.

PERCHE' NON BASTA ACCORGERSENE. python-telegram-bot non riprova: una chiamata
che fallisce a livello di trasporto diventa un'eccezione, e l'eccezione arriva
in faccia a chi ha scritto il comando. E' successo davvero, con un `/squadre`:
le squadre erano state rinominate, ma la conferma non e' partita e il bot ha
detto «qualcosa e' andato storto». Il peggio dei due mondi — il lavoro fatto e
l'utente convinto del contrario.

Durante un'asta questo non e' un fastidio, e' un rischio: chi legge «errore»
riscrive il comando, e un acquisto registrato due volte e' peggio di un
acquisto non registrato.

COSA SI RIPROVA E COSA NO. Solo gli errori di **collegamento**: il proxy che
non risponde, la connessione che non si apre. Non i timeout di lettura — li'
la richiesta puo' essere arrivata a Telegram, e rispedirla vorrebbe dire un
messaggio doppio. E non gli errori che Telegram stesso restituisce, che sono
risposte valide e vanno lette, non ripetute.

Riprovare le chiamate a Telegram e' comunque sicuro per l'asta: quello che
tocca le rose e' gia' stato scritto nel database prima, da noi. Al massimo
si duplica un messaggio in chat.
"""

from __future__ import annotations

import asyncio
import logging

from telegram.error import NetworkError, TimedOut
from telegram.request import HTTPXRequest

log = logging.getLogger(__name__)

# Quanto aspettare fra un tentativo e l'altro, in secondi. Corte e poche: un
# proxy che si riprende ci mette un istante, e mentre si aspetta il banditore
# non aspetta. Se dopo un secondo e mezzo in tutto non e' passata, non e' un
# intoppo — e allora e' giusto che l'errore si veda.
ATTESE = (0.4, 0.8, 1.6)


class RichiestaOstinata(HTTPXRequest):
    """Come `HTTPXRequest`, ma non si arrende al primo 503 del proxy."""

    async def do_request(self, *args, **kwargs):
        for numero, attesa in enumerate((*ATTESE, None)):
            try:
                return await super().do_request(*args, **kwargs)
            except TimedOut:
                # La richiesta puo' essere arrivata: rispedirla duplicherebbe.
                raise
            except NetworkError as errore:
                if attesa is None:
                    log.error(
                        "Telegram irraggiungibile dopo %s tentativi: %s",
                        numero,
                        errore,
                    )
                    raise
                log.warning(
                    "collegamento a Telegram fallito (%s), riprovo fra %ss",
                    errore,
                    attesa,
                )
                await asyncio.sleep(attesa)
        raise AssertionError("irraggiungibile")  # pragma: no cover
