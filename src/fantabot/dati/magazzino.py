"""Lettura del database verso gli oggetti del motore, e ricerca per nome.

Il motore non sa che esiste SQLite e il database non sa che esiste il motore:
qui in mezzo si traducono le righe in `Giocatore`, una volta sola per
richiesta.
"""

from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher

from ..motore.valutazione import (
    Fermo,
    Giocatore,
    Giudizi,
    InCampo,
    StagioneStat,
)
from . import squalifiche
from .aggiorna import normalizza

# Quanta parte del listone il file delle fasce deve coprire perche' le sue
# assenze valgano come smentite. Meta' e' larghissimo apposta: serve solo a
# distinguere una lista piu' corta da un import andato storto. Se domani un
# file combacia con trenta nomi su seicento, la risposta giusta non e'
# cancellare cinquecentosettanta giocatori la sera dell'asta — e' non filtrare
# niente e dirlo.
COPERTURA_MINIMA_FASCE = 0.5


def _campo(conn: sqlite3.Connection) -> tuple[dict[int, InCampo], dict[str, int]]:
    """Quanto ognuno sta giocando, e quante giornate ha giocato ogni squadra.

    Le giornate per squadra servono per chi NON ha una riga: chi non e' mai
    sceso in campo non compare nella fonte, e senza le giornate della sua
    squadra sarebbe indistinguibile da un giocatore di cui non si sa niente.
    Sono due cose opposte — la prima e' l'informazione piu' importante che
    esista a settembre, la seconda e' silenzio.
    """
    per_id: dict[int, InCampo] = {}
    giornate: dict[str, int] = {}
    for r in conn.execute(
        "SELECT c.*, g.squadra FROM campo c JOIN giocatori g ON g.id_fc = c.id_fc"
    ):
        per_id[r["id_fc"]] = InCampo(
            minuti=r["minuti"],
            presenze=r["presenze"],
            giornate=r["giornate_squadra"],
            previsto_titolare=(
                None if r["previsto_titolare"] is None else bool(r["previsto_titolare"])
            ),
        )
        giornate[r["squadra"]] = max(
            giornate.get(r["squadra"], 0), r["giornate_squadra"]
        )
    return per_id, giornate


def fuori_lista(conn: sqlite3.Connection) -> set[int]:
    """Chi sta nel listone ma non nel file delle fasce.

    Il listone di fantacalcio.it e' una fotografia che non si aggiorna quando
    uno cambia campionato: a mercato chiuso Leao risultava ancora al Milan, con
    il suo FVM da 75, e il bot lo consigliava. Il file delle fasce e' compilato
    a mano da chi il mercato lo ha seguito, quindi la sua assenza e' una
    notizia: quel giocatore non c'e' piu'.

    Non e' una regola simmetrica. Un nome nelle fasce ma non nel listone e' un
    problema diverso — un nome scritto in un altro modo — e lo dice gia'
    l'import, che elenca i non trovati.
    """
    totale = conn.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
    dentro = {
        r[0] for r in conn.execute("SELECT id_fc FROM mercato_esterno")
    }
    if not totale or len(dentro) < totale * COPERTURA_MINIMA_FASCE:
        return set()
    return {
        r[0]
        for r in conn.execute("SELECT id_fc FROM giocatori")
        if r[0] not in dentro
    }


def carica_giocatori(conn: sqlite3.Connection) -> list[Giocatore]:
    """Tutti i giocatori del listone, con lo storico attaccato."""
    storici: dict[int, list[StagioneStat]] = {}
    for r in conn.execute(
        """
        SELECT id_fc, stagione, squadra, presenze, fantamedia, media_voto,
               gol, assist, rigori_calciati, ammonizioni, espulsioni, giornate
        FROM statistiche ORDER BY stagione DESC
        """
    ):
        storici.setdefault(r["id_fc"], []).append(
            StagioneStat(
                stagione=r["stagione"],
                presenze=r["presenze"],
                fantamedia=r["fantamedia"],
                giornate=r["giornate"],
                squadra=r["squadra"],
                media_voto=r["media_voto"],
                gol=r["gol"],
                assist=r["assist"],
                rigori_calciati=r["rigori_calciati"],
                ammonizioni=r["ammonizioni"],
                espulsioni=r["espulsioni"],
            )
        )
    in_campo, giornate = _campo(conn)
    fermi = {
        r["id_fc"]: Fermo(
            giornate_fuori=r["giornate_fuori"],
            testo=r["testo"],
            datato=bool(r["datato"]),
        )
        for r in conn.execute(
            "SELECT id_fc, giornate_fuori, testo, datato FROM infortuni"
        )
    }
    giudizi = {
        r["id_fc"]: Giudizi(
            titolarita=r["titolarita"],
            integrita=r["integrita"],
            affidabilita=r["affidabilita"],
            note=tuple(
                n.strip().lower() for n in (r["note"] or "").split(",") if n.strip()
            ),
            fascia=r["fascia"],
        )
        for r in conn.execute(
            "SELECT id_fc, titolarita, integrita, affidabilita, note, fascia"
            " FROM mercato_esterno"
            " WHERE titolarita IS NOT NULL OR integrita IS NOT NULL"
            " OR affidabilita IS NOT NULL OR note != '' OR fascia IS NOT NULL"
        )
    }
    fuori = fuori_lista(conn)
    fermi_per_cartellini = squalifiche.carica(conn)
    giocatori = []
    for r in conn.execute(
        "SELECT id_fc, nome, squadra, ruolo, quota_attuale, fvm FROM giocatori"
    ):
        campo = in_campo.get(r["id_fc"])
        if campo is None and giornate.get(r["squadra"], 0) > 0:
            # La sua squadra ha giocato e lui non compare: zero minuti. E'
            # un dato, non un buco.
            campo = InCampo(
                minuti=0, presenze=0, giornate=giornate[r["squadra"]]
            )
        giocatori.append(
            Giocatore(
                id_fc=r["id_fc"],
                nome=r["nome"],
                squadra=r["squadra"],
                ruolo=r["ruolo"],
                quota=r["quota_attuale"],
                fvm=r["fvm"],
                storico=tuple(storici.get(r["id_fc"], ())),
                campo=campo,
                fermo=fermi.get(r["id_fc"]),
                giudizi=giudizi.get(r["id_fc"]),
                in_lista=r["id_fc"] not in fuori,
                squalificato=fermi_per_cartellini.get(r["id_fc"], (0, False, ""))[0],
                diffidato=fermi_per_cartellini.get(r["id_fc"], (0, False, ""))[1],
            )
        )
    return giocatori


def cerca(
    conn: sqlite3.Connection, testo: str, *, limite: int = 8
) -> list[sqlite3.Row]:
    """Cerca un giocatore per nome, perdonando errori di battitura.

    All'asta si scrive di fretta. Prima si prova il prefisso (chi digita
    "vla" vuole Vlahovic e lo vuole subito), poi il pezzo di parola, e solo
    se non basta si passa alla somiglianza, che costa di piu' ma salva
    "donnaruma".
    """
    chiave = normalizza(testo)
    if not chiave:
        return []
    righe = conn.execute(
        """
        SELECT id_fc, nome, nome_cerca, squadra, ruolo, quota_attuale, fvm
        FROM giocatori
        """
    ).fetchall()

    prefisso = [r for r in righe if r["nome_cerca"].startswith(chiave)]
    if prefisso:
        return sorted(prefisso, key=lambda r: -r["fvm"])[:limite]

    dentro = [r for r in righe if chiave in r["nome_cerca"]]
    if dentro:
        return sorted(dentro, key=lambda r: -r["fvm"])[:limite]

    simili = [
        (SequenceMatcher(None, chiave, r["nome_cerca"]).ratio(), r) for r in righe
    ]
    simili = [(punteggio, r) for punteggio, r in simili if punteggio >= 0.62]
    simili.sort(key=lambda coppia: (-coppia[0], -coppia[1]["fvm"]))
    return [r for _, r in simili[:limite]]
