"""Quanto due squadre si abbinano bene, per chi ne schiera uno solo alla volta.

PERCHE' ESISTE. Portieri e attaccanti hanno un problema che difensori e
centrocampisti non hanno: ne giochi pochi — un portiere, due o tre attaccanti —
e quindi il calendario conta quanto il giocatore. Due portieri di squadre che
affrontano le grandi nella stessa giornata sono un portiere e mezzo; due che si
alternano bene sono due portieri sempre buoni.

Il punteggio di un abbinamento non lo calcola questo bot: lo pubblica FantaLab
come matrice ventina per ventina, ed e' il risultato di incrociare i due
calendari giornata per giornata. Qui si importa e si usa.

COSA E' UNA MATRICE VALIDA. Prima riga e prima colonna con le sigle delle
squadre, dentro i numeri, e la diagonale vuota. Deve essere **simmetrica**:
l'abbinamento Lecce-Napoli e quello Napoli-Lecce sono la stessa cosa, e se le
due meta' non coincidono qualcosa e' stato letto male. Il controllo non e'
formalita': la prima versione di questa tabella e' stata trascritta a mano da
uno screenshot, e la simmetria e' l'unica cosa che poteva dire se la
trascrizione reggeva. (Reggeva: 380 celle, zero disaccordi.)

COSA NON PUO' FARE. Il punteggio e' di stagione, non di giornata: dice quali
due squadre stanno bene insieme, non quale dei due portieri schierare domenica
prossima. Per quello servirebbe il calendario giornata per giornata, che il
bot non ha.
"""

from __future__ import annotations

import csv
import io
import itertools
import logging
import sqlite3
from dataclasses import dataclass, field

from ..config import RADICE

log = logging.getLogger(__name__)

SEMI = RADICE / "dati" / "coppie"
NOMI_FILE = {"p": "portieri.csv", "a": "attaccanti.csv"}


@dataclass
class Esito:
    ruolo: str = ""
    coppie: int = 0
    asimmetrie: list[tuple[str, str]] = field(default_factory=list)
    errore: str = ""

    @property
    def riuscito(self) -> bool:
        return not self.errore and self.coppie > 0


def leggi_matrice(testo: str) -> tuple[dict[tuple[str, str], int], list[tuple[str, str]]]:
    """La matrice come dizionario di coppie, e i disaccordi fra le due meta'.

    Le sigle si normalizzano a maiuscolo perche' un export puo' scriverle come
    viene, e una coppia si tiene una volta sola in ordine alfabetico: e' lo
    stesso abbinamento letto da due lati.
    """
    righe = [r for r in csv.reader(io.StringIO(testo)) if any(c.strip() for c in r)]
    if len(righe) < 3:
        return {}, []
    teste = [c.strip().upper() for c in righe[0][1:]]
    grezzo: dict[tuple[str, str], int] = {}
    for riga in righe[1:]:
        sigla = riga[0].strip().upper()
        if not sigla:
            continue
        for altra, valore in zip(teste, riga[1:], strict=False):
            testo_cella = (valore or "").strip().replace(",", ".")
            if not testo_cella or altra == sigla:
                continue
            try:
                grezzo[(sigla, altra)] = round(float(testo_cella))
            except ValueError:
                continue

    coppie: dict[tuple[str, str], int] = {}
    asimmetrie: list[tuple[str, str]] = []
    for a, b in itertools.combinations(sorted({s for s, _ in grezzo}), 2):
        andata, ritorno = grezzo.get((a, b)), grezzo.get((b, a))
        if andata is None and ritorno is None:
            continue
        if andata is not None and ritorno is not None and andata != ritorno:
            asimmetrie.append((a, b))
            continue
        coppie[(a, b)] = andata if andata is not None else ritorno
    return coppie, asimmetrie


def salva(conn: sqlite3.Connection, ruolo: str, coppie: dict, fonte: str = "") -> None:
    conn.execute("DELETE FROM coppie WHERE ruolo = ?", (ruolo,))
    conn.executemany(
        "INSERT INTO coppie (ruolo, sigla_a, sigla_b, punteggio, fonte)"
        " VALUES (?, ?, ?, ?, ?)",
        [(ruolo, a, b, v, fonte) for (a, b), v in coppie.items()],
    )
    conn.commit()


def importa(
    conn: sqlite3.Connection, testo: str, ruolo: str, fonte: str = ""
) -> Esito:
    """Legge una matrice e la salva, se sta in piedi."""
    esito = Esito(ruolo=ruolo)
    coppie, asimmetrie = leggi_matrice(testo)
    esito.asimmetrie = asimmetrie
    if not coppie:
        esito.errore = (
            "non riconosco una matrice: serve la prima riga e la prima colonna "
            "con le sigle delle squadre, e i punteggi dentro."
        )
        return esito
    if asimmetrie:
        # NON SI IMPORTA A META'. Una matrice che si contraddice e' una matrice
        # letta male, e importarne la parte buona nasconderebbe l'errore invece
        # di mostrarlo.
        esito.errore = (
            f"{len(asimmetrie)} abbinamenti non coincidono fra le due meta' "
            "della tabella: e' segno che qualcosa e' stato letto male."
        )
        return esito
    salva(conn, ruolo, coppie, fonte)
    esito.coppie = len(coppie)
    return esito


def carica_semi(conn: sqlite3.Connection) -> dict[str, int]:
    """Le matrici che il progetto porta con se', se non ce n'e' gia' una.

    Non sovrascrivono mai quello che hai importato tu: un file caricato a mano
    e' piu' recente e piu' tuo di uno che sta nel repository.
    """
    esito: dict[str, int] = {}
    for ruolo, nome in NOMI_FILE.items():
        percorso = SEMI / nome
        if not percorso.exists():
            continue
        gia = conn.execute(
            "SELECT COUNT(*) FROM coppie WHERE ruolo = ?", (ruolo,)
        ).fetchone()[0]
        if gia:
            continue
        letto = importa(
            conn, percorso.read_text(encoding="utf-8"), ruolo, fonte=nome
        )
        if letto.riuscito:
            esito[ruolo] = letto.coppie
        else:
            log.warning("seme %s non caricato: %s", nome, letto.errore)
    return esito


def leggi(conn: sqlite3.Connection, ruolo: str) -> dict[tuple[str, str], int]:
    return {
        (r["sigla_a"], r["sigla_b"]): r["punteggio"]
        for r in conn.execute(
            "SELECT sigla_a, sigla_b, punteggio FROM coppie WHERE ruolo = ?", (ruolo,)
        )
    }


def punteggio(coppie: dict[tuple[str, str], int], a: str, b: str) -> int | None:
    """L'abbinamento fra due squadre, da qualunque lato lo si chieda."""
    if a == b:
        return None
    return coppie.get((min(a, b), max(a, b)))


def migliori_per(
    coppie: dict[tuple[str, str], int], sigla: str, quante: int = 5
) -> list[tuple[str, int]]:
    """Con chi si abbina meglio una squadra, dalla migliore."""
    trovate = [
        (b if a == sigla else a, v)
        for (a, b), v in coppie.items()
        if sigla in (a, b)
    ]
    trovate.sort(key=lambda t: -t[1])
    return trovate[:quante]
