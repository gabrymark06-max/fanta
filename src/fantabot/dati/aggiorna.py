"""Porta listone e statistiche dentro il database.

Si lancia a mano (`python -m fantabot.dati.aggiorna`) o dal bot con
`/aggiorna`. E' idempotente: rilanciarlo due volte di fila non duplica nulla e
non tocca la rosa gia' comprata all'asta.
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata

import httpx

from ..db import connetti, transazione
from . import andamento, fantacalcio

log = logging.getLogger(__name__)


def normalizza(testo: str) -> str:
    """La forma con cui si cerca un giocatore: niente accenti, niente punti.

    Chi scrive al bot durante l'asta digita "vlahovic" con il telefono in una
    mano: "Vlahović", "Vlahovic" e "vlahovic" devono essere la stessa cosa.
    """
    piatto = unicodedata.normalize("NFKD", testo)
    piatto = "".join(c for c in piatto if not unicodedata.combining(c))
    tenuti = [c.lower() if (c.isalnum() or c.isspace()) else " " for c in piatto]
    return " ".join("".join(tenuti).split())


def _coppia_rigori(grezzo: str) -> tuple[int, int]:
    """La cella dei rigori vale "3 / 4": segnati su calciati."""
    pezzi = [p.strip() for p in (grezzo or "").split("/")]
    numeri = [int(p) if p.isdigit() else 0 for p in pezzi]
    if len(numeri) == 1:
        return numeri[0], 0
    return numeri[0], numeri[1]


def aggiorna(
    conn: sqlite3.Connection | None = None, *, client: httpx.Client | None = None
) -> dict[str, int]:
    """Scarica e salva. Restituisce quante righe ha scritto, per tipo."""
    conn = conn or connetti()
    proprio = client is None
    client = client or httpx.Client(
        headers=fantacalcio.INTESTAZIONI, timeout=30.0, follow_redirects=True
    )
    try:
        listone = fantacalcio.leggi_listone(client=client)
        with transazione(conn):
            conn.executemany(
                """
                INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                                       ruolo_mantra, quota_iniziale,
                                       quota_attuale, fvm, aggiornato_il)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id_fc) DO UPDATE SET
                    nome = excluded.nome,
                    nome_cerca = excluded.nome_cerca,
                    squadra = excluded.squadra,
                    ruolo = excluded.ruolo,
                    ruolo_mantra = excluded.ruolo_mantra,
                    quota_iniziale = excluded.quota_iniziale,
                    quota_attuale = excluded.quota_attuale,
                    fvm = excluded.fvm,
                    aggiornato_il = datetime('now')
                """,
                [
                    (
                        r.id_fc,
                        r.nome,
                        normalizza(r.nome),
                        r.squadra,
                        r.ruolo_classic or "?",
                        r.ruolo_mantra,
                        int(r.numero("c_qi", 1)) or 1,
                        int(r.numero("c_qa", 1)) or 1,
                        int(r.numero("c_fvm", 0)),
                    )
                    for r in listone
                ],
            )

        scritte_stat = 0
        for stagione in fantacalcio.stagioni_statistiche():
            try:
                righe = fantacalcio.leggi_statistiche(stagione, client=client)
            except Exception:
                # Una stagione storica che non risponde non deve impedire
                # l'aggiornamento del listone, che e' la parte che serve
                # davvero all'asta.
                continue
            # SU QUANTE GIORNATE POGGIA QUESTA RIGA. Non c'e' un campo che lo
            # dica, e non serve: la giornata piu' alta a cui qualcuno e'
            # arrivato E' la giornata a cui e' arrivato il campionato. Per una
            # stagione conclusa fa 38 e non cambia niente; per quella in corso
            # e' l'unica cosa che distingue "tre partite finora" da "tre
            # partite in tutto l'anno".
            giornate = max((int(r.numero("pg")) for r in righe), default=38)
            with transazione(conn):
                conn.executemany(
                    """
                    INSERT INTO statistiche (
                        id_fc, stagione, squadra, presenze, media_voto,
                        fantamedia, gol, gol_subiti, assist, ammonizioni,
                        espulsioni, rigori_segnati, rigori_calciati,
                        rigori_parati, giornate)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id_fc, stagione) DO UPDATE SET
                        squadra = excluded.squadra,
                        giornate = excluded.giornate,
                        presenze = excluded.presenze,
                        media_voto = excluded.media_voto,
                        fantamedia = excluded.fantamedia,
                        gol = excluded.gol,
                        gol_subiti = excluded.gol_subiti,
                        assist = excluded.assist,
                        ammonizioni = excluded.ammonizioni,
                        espulsioni = excluded.espulsioni,
                        rigori_segnati = excluded.rigori_segnati,
                        rigori_calciati = excluded.rigori_calciati,
                        rigori_parati = excluded.rigori_parati
                    """,
                    [
                        (
                            r.id_fc,
                            stagione,
                            r.squadra,
                            int(r.numero("pg")),
                            r.numero("mv"),
                            r.numero("mfv"),
                            int(r.numero("gol")),
                            int(r.numero("gs")),
                            int(r.numero("ass")),
                            int(r.numero("amm")),
                            int(r.numero("esp")),
                            *_coppia_rigori(r.valori.get("rig", "")),
                            int(r.numero("rp")),
                            giornate,
                        )
                        for r in righe
                    ],
                )
                scritte_stat += len(righe)
            if stagione == fantacalcio.STAGIONE_CORRENTE and giornate > 0:
                # La fotografia della giornata appena letta. Da qui in poi la
                # differenza fra due giornate dice cosa e' successo domenica,
                # che il cumulato da solo non racconta.
                andamento.fotografa(conn, giornate)
        return {"giocatori": len(listone), "statistiche": scritte_stat}
    finally:
        if proprio:
            client.close()


def aggiorna_tutto(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Tutte le fonti, nell'ordine giusto, dietro una chiamata sola.

    L'ORDINE NON E' CASUALE e per questo non si ripete altrove:

      1. listone e statistiche, che stabiliscono a che giornata siamo;
      2. il campo, che porta i minuti di quella giornata;
      3. la fotografia, che deve venire DOPO i minuti — presa prima
         registrerebbe i minuti del giro precedente accanto ai gol di questo,
         e la differenza fra due fotografie diventerebbe un miscuglio;
      4. gli infortunati, che per contare le giornate di stop hanno bisogno di
         sapere a che giornata siamo, cioe' del passo 2;
      5. le squalifiche, che non dipendono da niente ma valgono solo per la
         settimana in cui si leggono.

    Una fonte che non risponde non ferma le altre: a stagione in corso e' molto
    peggio non sapere niente che sapere tre cose su quattro.
    """
    from . import campo, infortuni, squalifiche

    conn = conn or connetti()
    esito = dict(aggiorna(conn))
    fonti = (
        ("campo", campo.aggiorna),
        ("infortuni", infortuni.aggiorna),
        ("squalifiche", _squalifiche(squalifiche)),
    )
    for nome, funzione in fonti:
        try:
            parziale = funzione(conn)
        except Exception:  # la rete puo' sempre andare male
            log.exception("aggiornamento di %s fallito", nome)
            continue
        esito.update(parziale)
        if nome == "campo" and esito.get("giornate"):
            andamento.fotografa(conn, esito["giornate"])
    return esito


def _squalifiche(modulo):
    """Le squalifiche in una forma che somiglia alle altre fonti."""

    def leggi(conn):
        esito = modulo.aggiorna(conn)
        if esito.errore:
            raise RuntimeError(esito.errore)
        return {"squalificati": len(esito.squalificati),
                "diffidati": len(esito.diffidati)}

    return leggi


if __name__ == "__main__":
    esito = aggiorna_tutto()
    print(
        f"Listone: {esito['giocatori']} giocatori. "
        f"Statistiche: {esito['statistiche']} righe. "
        f"Giornata {esito.get('giornate', 0)}, "
        f"{esito.get('fermi', 0)} infortunati."
    )
