"""Lettura del listone e delle statistiche dalle pagine pubbliche di fantacalcio.it.

L'export Excel ufficiale (`/api/v1/Excel/prices/...`) risponde 401 senza
sessione: non lo usiamo. Le due pagine pubbliche contengono invece gia' tutto,
nella stessa struttura HTML — una tabella di `tr.player-row` in cui ogni cella
si dichiara con `data-col-key`. Un solo parser le legge entrambe.

L'aggancio fra listone e statistiche e' **l'id numerico nell'URL della scheda**
(`/serie-a/squadre/<squadra>/<slug>/5585`), mai il nome: due giocatori possono
chiamarsi "Pereira" e lo stesso giocatore cambia squadra a gennaio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from ..config import CACHE, STAGIONE_CORRENTE, STAGIONE_PRECEDENTE

BASE = "https://www.fantacalcio.it"
# Senza uno User-Agent da browser il sito risponde con una pagina di sfida.
INTESTAZIONI = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}
# L'id e' il penultimo segmento quando l'URL porta anche la stagione
# (`/malen/5585/2025-26`), l'ultimo quando non la porta (`/malen/5585`).
ID_NELL_URL = re.compile(r"/(\d+)(?:/\d{4}-\d{2})?/?$")


@dataclass(frozen=True)
class RigaGiocatore:
    """Una riga di tabella, prima di sapere se e' listone o statistiche."""

    id_fc: int
    nome: str
    squadra: str
    ruolo_classic: str
    ruolo_mantra: str
    valori: dict[str, str] = field(default_factory=dict)

    def numero(self, chiave: str, default: float = 0.0) -> float:
        """Il valore di una colonna come numero, tollerante al formato.

        Le celle vuote esistono (un giocatore senza presenze non ha media
        voto) e la virgola decimale italiana pure. Nessuna delle due deve
        far esplodere l'aggiornamento di seicento giocatori.
        """
        grezzo = (self.valori.get(chiave) or "").strip().replace(",", ".")
        if not grezzo or grezzo in {"-", "—"}:
            return default
        try:
            return float(grezzo)
        except ValueError:
            return default


def _scarica(url: str, *, nome_cache: str, client: httpx.Client | None = None) -> str:
    """Scarica una pagina e ne tiene una copia su disco.

    La copia serve al giorno dell'asta: se il sito e' lento o irraggiungibile
    proprio mentre chiami un giocatore, il bot lavora sull'ultimo listone
    scaricato invece di non rispondere.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    percorso = CACHE / nome_cache
    proprio = client is None
    client = client or httpx.Client(
        headers=INTESTAZIONI, timeout=30.0, follow_redirects=True
    )
    try:
        risposta = client.get(url)
        risposta.raise_for_status()
        percorso.write_text(risposta.text, encoding="utf-8")
        return risposta.text
    except Exception:
        if percorso.exists():
            return percorso.read_text(encoding="utf-8")
        raise
    finally:
        if proprio:
            client.close()


def analizza_tabella(html: str) -> list[RigaGiocatore]:
    """Estrae le righe giocatore da una qualunque tabella di fantacalcio.it."""
    zuppa = BeautifulSoup(html, "lxml")
    righe: list[RigaGiocatore] = []
    for tr in zuppa.select("tr.player-row"):
        link = tr.select_one("a.player-link")
        if link is None:
            continue
        trovato = ID_NELL_URL.search(link.get("href", ""))
        if trovato is None:
            continue
        nome = link.get_text(strip=True)
        if not nome:
            continue
        valori = {
            cella["data-col-key"]: cella.get_text(strip=True)
            for cella in tr.select("[data-col-key]")
            if cella.get("data-col-key")
        }
        ruolo_classic = (tr.get("data-filter-role-classic") or "").strip().lower()
        ruolo_mantra = (tr.get("data-filter-role-mantra") or "").strip().lower()
        righe.append(
            RigaGiocatore(
                id_fc=int(trovato.group(1)),
                nome=nome,
                squadra=(valori.get("sq") or "").strip().upper(),
                ruolo_classic=ruolo_classic,
                ruolo_mantra=ruolo_mantra,
                valori=valori,
            )
        )
    return righe


def leggi_listone(client: httpx.Client | None = None) -> list[RigaGiocatore]:
    """Il listone della stagione in corso: ruoli, quotazioni, FVM."""
    html = _scarica(
        f"{BASE}/quotazioni-fantacalcio",
        nome_cache="quotazioni.html",
        client=client,
    )
    righe = analizza_tabella(html)
    if len(righe) < 200:
        raise RuntimeError(
            f"Il listone ha solo {len(righe)} righe: la pagina e' cambiata "
            "o e' arrivata una pagina di sfida. Non aggiorno il database."
        )
    return righe


def leggi_statistiche(
    stagione: str = STAGIONE_PRECEDENTE, client: httpx.Client | None = None
) -> list[RigaGiocatore]:
    """Il riepilogo statistico di una stagione: presenze, medie, bonus."""
    html = _scarica(
        f"{BASE}/statistiche-serie-a/{stagione}/classic/riepilogo",
        nome_cache=f"statistiche-{stagione}.html",
        client=client,
    )
    return analizza_tabella(html)


def stagioni_statistiche() -> tuple[str, ...]:
    """Le stagioni che il motore usa, dalla piu' recente.

    Due storiche e non una: chi ha fatto bene un anno solo puo' essere stato
    fortunato, chi ne ha fatti due di fila di solito no.

    E QUELLA IN CORSO, che a settembre e' lunga tre giornate e vale comunque
    la pena leggere: e' l'unico posto in cui compaiono i bonus di chi in Serie
    A non ha uno storico. Il 6 settembre 2026 diceva che Malen aveva segnato
    cinque gol in tre partite, che e' la ragione per cui costava
    duecentoquarantacinque crediti — e senza questa riga il bot non poteva
    saperlo. Quanto pesa lo decide `motore/valutazione.py`, che la pesa per
    presenze e a tre giornate le da' pochissimo.
    """
    anno = int(STAGIONE_CORRENTE.split("-")[0])
    return (STAGIONE_CORRENTE,) + tuple(
        f"{a}-{str(a + 1)[-2:]}" for a in (anno - 1, anno - 2)
    )
