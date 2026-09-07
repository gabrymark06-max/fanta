"""Un listone finto ma realistico, per provare il motore senza rete.

I numeri non sono presi da una stagione vera: sono costruiti perche' ogni
ruolo abbia un campione, una schiera di titolari, e una coda di gente che
all'asta va a un credito. E' la forma che conta, ed e' quella che rompe il
codice quando e' sbagliato.
"""

from __future__ import annotations

import pytest

from fantabot.db import connetti
from fantabot.motore.valutazione import Giocatore, ParametriLega, StagioneStat


def _giocatore(indice: int, ruolo: str, forza: float) -> Giocatore:
    """forza va da 1.0 (campione) a 0.0 (ultimo del listone)."""
    fantamedia = {"p": 5.0, "d": 5.8, "c": 5.9, "a": 6.0}[ruolo] + 2.0 * forza
    presenze = int(6 + 30 * forza)
    quota = max(1, int(1 + 36 * forza**2))
    fvm = max(1, int(1 + 440 * forza**3))
    return Giocatore(
        id_fc=indice,
        nome=f"{ruolo.upper()}{indice:03d}",
        squadra="TST",
        ruolo=ruolo,
        quota=quota,
        fvm=fvm,
        storico=(
            StagioneStat(
                "2025-26", presenze, fantamedia, media_voto=fantamedia - 0.6
            ),
            StagioneStat(
                "2024-25",
                max(0, presenze - 3),
                fantamedia - 0.1,
                media_voto=fantamedia - 0.7,
            ),
        ),
    )


@pytest.fixture
def parametri() -> ParametriLega:
    return ParametriLega(crediti=500, n_squadre=8, slot={"p": 3, "d": 8, "c": 8, "a": 6})


@pytest.fixture
def listone() -> list[Giocatore]:
    """Piu' giocatori di quanti la lega ne comprera': serve la coda."""
    quanti = {"p": 40, "d": 100, "c": 100, "a": 70}
    giocatori = []
    indice = 1
    for ruolo, n in quanti.items():
        for posizione in range(n):
            forza = 1.0 - posizione / n
            giocatori.append(_giocatore(indice, ruolo, forza))
            indice += 1
    return giocatori


@pytest.fixture
def conn():
    c = connetti(":memory:")
    yield c
    c.close()


@pytest.fixture
def conn_popolato(conn, listone):
    conn.executemany(
        """
        INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                               quota_iniziale, quota_attuale, fvm)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (g.id_fc, g.nome, g.nome.lower(), g.squadra, g.ruolo, g.quota, g.quota, g.fvm)
            for g in listone
        ],
    )
    conn.executemany(
        """
        INSERT INTO statistiche (id_fc, stagione, presenze, fantamedia, media_voto)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (g.id_fc, s.stagione, s.presenze, s.fantamedia, s.media_voto)
            for g in listone
            for s in g.storico
        ],
    )
    conn.commit()
    return conn
