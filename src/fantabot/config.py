"""Configurazione: percorsi e segreti, letti una volta sola.

Il token del bot non compare mai nel codice ne' nel database: sta in `.env`,
che e' in `.gitignore`, oppure nell'ambiente reale quando il bot gira su un
server. Se manca, il bot non parte e lo dice chiaramente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
DATI = RADICE / "dati"
DB = DATI / "fantabot.sqlite3"
CACHE = DATI / "cache"

# La stagione in corso e quella appena conclusa, nel formato usato negli URL
# di fantacalcio.it. Si aggiornano una volta l'anno, qui e in nessun altro
# posto.
STAGIONE_CORRENTE = "2026-27"
STAGIONE_PRECEDENTE = "2025-26"


def _carica_env() -> None:
    """Legge `.env` senza sovrascrivere l'ambiente gia' impostato.

    Il file scritto su Windows ha spesso un BOM: si legge con utf-8-sig,
    altrimenti la prima chiave si chiamerebbe '\ufeffTELEGRAM_BOT_TOKEN'.
    """
    percorso = RADICE / ".env"
    if not percorso.exists():
        return
    for riga_grezza in percorso.read_text(encoding="utf-8-sig").splitlines():
        riga = riga_grezza.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, valore = riga.split("=", 1)
        chiave, valore = chiave.strip(), valore.strip().strip('"').strip("'")
        if chiave and chiave not in os.environ:
            os.environ[chiave] = valore


@dataclass(frozen=True)
class Impostazioni:
    token_telegram: str
    # Chi puo' usare il bot. Vuoto = chiunque, e va bene solo in sviluppo:
    # un assistente d'asta che chiunque puo' pilotare e' un assistente
    # dell'avversario.
    utenti_ammessi: frozenset[int]

    def utente_ammesso(self, id_telegram: int) -> bool:
        return not self.utenti_ammessi or id_telegram in self.utenti_ammessi


@lru_cache(maxsize=1)
def impostazioni() -> Impostazioni:
    _carica_env()
    grezzi = os.environ.get("UTENTI_AMMESSI", "").replace(";", ",")
    ammessi = frozenset(
        int(pezzo.strip())
        for pezzo in grezzi.split(",")
        if pezzo.strip().lstrip("-").isdigit()
    )
    return Impostazioni(
        token_telegram=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        utenti_ammessi=ammessi,
    )
