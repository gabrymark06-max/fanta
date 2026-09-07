"""Cosa e' successo giornata per giornata, ricavato dai totali.

PERCHE' ESISTE. Fantacalcio pubblica solo cumulati: «5 gol, fantamedia 12,33,
3 presenze». Da un cumulato non si ricava cosa e' successo domenica scorsa, e
domenica scorsa e' esattamente quello che serve sapere per schierare — un
attaccante fermo a 5 in fantamedia da tre turni e uno che ne ha appena presi
due da 9 hanno la stessa media di stagione e non sono la stessa cosa.

LA SOLUZIONE NON E' UNA FONTE IN PIU'. Basta conservare la fotografia dei
totali a ogni giornata: **la differenza fra due fotografie E' la giornata**.
Costa una tabella e nessuna richiesta aggiuntiva, e ha il pregio di non poter
divergere dal cumulato — perche' e' il cumulato.

COSA NON PUO' FARE. Se il bot non gira per tre giornate, quelle tre diventano
un blocco solo: la differenza fra la fotografia della 4a e quella della 7a e'
la somma di tre turni, e questo modulo lo dichiara invece di spalmarla. Un
numero medio spacciato per una giornata sarebbe peggio di un buco onesto.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

CAMPI = (
    "presenze",
    "media_voto",
    "fantamedia",
    "gol",
    "assist",
    "ammonizioni",
    "espulsioni",
    "gol_subiti",
    "minuti",
)

# Quante giornate guardare per dire "come sta adesso". Tre e' il compromesso
# solito fra il rumore di una domenica e la lentezza di un mese.
GIORNATE_DI_FORMA = 3


@dataclass(frozen=True)
class Turno:
    """Cosa ha fatto un giocatore in una giornata, o in un blocco di giornate."""

    giornata: int
    # Quante giornate copre davvero questa riga: 1 quasi sempre, di piu' se il
    # bot non ha letto per un po'. Vive qui perche' altrimenti un blocco di
    # tre turni si leggerebbe come una domenica clamorosa.
    coperte: int
    presenze: int
    gol: int
    assist: int
    ammonizioni: int
    espulsioni: int
    gol_subiti: int
    minuti: int
    # La fantamedia delle sole giornate coperte, quando ha giocato.
    fantamedia: float | None
    media_voto: float | None

    @property
    def giocata(self) -> bool:
        return self.presenze > 0


def fotografa(conn: sqlite3.Connection, giornata: int) -> int:
    """Salva i totali di adesso come la fotografia di questa giornata.

    Rileggere due volte la stessa giornata sovrascrive: la fotografia e' uno
    stato, non un evento, e sommarla due volte raddoppierebbe una stagione.
    """
    if giornata <= 0:
        return 0
    righe = conn.execute(
        """
        SELECT s.id_fc, s.presenze, s.media_voto, s.fantamedia, s.gol, s.assist,
               s.ammonizioni, s.espulsioni, s.gol_subiti,
               coalesce(c.minuti, 0) AS minuti
        FROM statistiche s
        LEFT JOIN campo c ON c.id_fc = s.id_fc
        WHERE s.giornate < 38
        """
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO andamento (id_fc, giornata, presenze, media_voto, fantamedia,
                               gol, assist, ammonizioni, espulsioni, gol_subiti,
                               minuti, letto_il)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id_fc, giornata) DO UPDATE SET
            presenze = excluded.presenze,
            media_voto = excluded.media_voto,
            fantamedia = excluded.fantamedia,
            gol = excluded.gol,
            assist = excluded.assist,
            ammonizioni = excluded.ammonizioni,
            espulsioni = excluded.espulsioni,
            gol_subiti = excluded.gol_subiti,
            minuti = excluded.minuti,
            letto_il = datetime('now')
        """,
        [
            (r["id_fc"], giornata, *(r[c] for c in CAMPI))
            for r in righe
        ],
    )
    conn.commit()
    return len(righe)


def _differenza(prima: sqlite3.Row | None, dopo: sqlite3.Row, coperte: int) -> Turno:
    """Quello che sta fra due fotografie."""

    def delta(campo: str) -> float:
        return dopo[campo] - (prima[campo] if prima is not None else 0)

    presenze = int(delta("presenze"))
    # LA FANTAMEDIA NON SI SOTTRAE: e' una media, e la differenza fra due medie
    # non e' la media della differenza. Si ricostruiscono i totali — media per
    # presenze — e si divide per le presenze di questo pezzo.
    def media(campo: str) -> float | None:
        if presenze <= 0:
            return None
        totale = dopo[campo] * dopo["presenze"] - (
            prima[campo] * prima["presenze"] if prima is not None else 0.0
        )
        return round(totale / presenze, 2)

    return Turno(
        giornata=dopo["giornata"],
        coperte=coperte,
        presenze=presenze,
        gol=int(delta("gol")),
        assist=int(delta("assist")),
        ammonizioni=int(delta("ammonizioni")),
        espulsioni=int(delta("espulsioni")),
        gol_subiti=int(delta("gol_subiti")),
        minuti=int(delta("minuti")),
        fantamedia=media("fantamedia"),
        media_voto=media("media_voto"),
    )


def turni(conn: sqlite3.Connection, id_fc: int) -> list[Turno]:
    """Giornata per giornata, dalla piu' recente."""
    righe = conn.execute(
        "SELECT * FROM andamento WHERE id_fc = ? ORDER BY giornata", (id_fc,)
    ).fetchall()
    esito: list[Turno] = []
    for i, riga in enumerate(righe):
        prima = righe[i - 1] if i else None
        coperte = riga["giornata"] - (prima["giornata"] if prima is not None else 0)
        esito.append(_differenza(prima, riga, max(1, coperte)))
    esito.reverse()
    return esito


def forma(
    conn: sqlite3.Connection, id_fc: int, quante: int = GIORNATE_DI_FORMA
) -> Turno | None:
    """Le ultime giornate messe insieme: come sta adesso, non com'e' l'annata.

    Torna `None` quando non c'e' abbastanza storia: a inizio stagione, o per
    chi non ha ancora una fotografia. Meglio niente che una forma costruita su
    una domenica sola.
    """
    righe = conn.execute(
        "SELECT * FROM andamento WHERE id_fc = ? ORDER BY giornata DESC LIMIT ?",
        (id_fc, quante + 1),
    ).fetchall()
    if len(righe) < 2:
        return None
    dopo, prima = righe[0], righe[-1]
    return _differenza(prima, dopo, dopo["giornata"] - prima["giornata"])


def ultima_giornata(conn: sqlite3.Connection) -> int:
    riga = conn.execute("SELECT MAX(giornata) FROM andamento").fetchone()
    return (riga[0] if riga else 0) or 0
