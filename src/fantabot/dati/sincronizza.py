"""Portare i dati letti altrove dentro il database che sta girando.

IL PROBLEMA. PythonAnywhere gratis non raggiunge fantacalcio.it, fotmob e
sportsgambler: la sua whitelist ha `api.telegram.org` e non le altre. Ma
GitHub Actions raggiunge tutto e non costa niente. Quindi si divide il lavoro:
Actions **legge** il mondo, PythonAnywhere **risponde** su Telegram, e in mezzo
passa un file.

LA TRAPPOLA, che e' il motivo per cui questo modulo esiste invece di un `scp`.
Il database contiene due cose diverse nello stesso file:

  · quello che si puo' RILEGGERE dal mondo — listone, statistiche, minuti,
    infortuni, squalifiche, calendario, abbinamenti. Se si perde, `/aggiorna`
    lo riporta indietro;
  · quello che ESISTE SOLO QUI — la tua lega, le rose, i prezzi pagati, i tuoi
    obiettivi, e il foglio delle fasce che hai caricato a mano da Telegram.
    Se si perde, e' perso.

Sovrascrivere il file intero avrebbe funzionato benissimo per undici giorni e
poi, il dodicesimo, avrebbe cancellato l'asta a meta' asta. Quindi non si
sovrascrive: si sostituiscono **solo le tabelle rileggibili**, in una
transazione sola, e le altre non vengono nemmeno aperte.

IL CONTROLLO CHE TIENE. Ogni tabella dello schema deve stare in esattamente
uno dei due elenchi qui sotto. Non e' una convenzione da ricordare: c'e' un
test che lo verifica, e una migrazione futura che aggiunge una tabella senza
classificarla fa fallire la suite invece di far sparire dei dati sei mesi dopo.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Si rileggono dal mondo: viaggiano da GitHub Actions verso il bot.
DI_RIFERIMENTO = (
    "giocatori",
    "statistiche",
    "campo",
    "infortuni",
    "squalifiche",
    "calendario",
    "coppie",
)

# Esistono solo dove gira il bot, e non si toccano mai.
#
# `mercato_esterno` sta qui e non fra le altre, anche se somiglia a un dato
# importato: arriva dal foglio che carichi TU su Telegram, e Actions non ha
# modo di rifarlo. `andamento` sta qui perche' e' una storia che si accumula —
# si ricostruisce dalle statistiche appena arrivate, sul posto, e non ha
# bisogno di viaggiare.
MIE = (
    "leghe",
    "squadre",
    "acquisti",
    "preferenze",
    "mercato_esterno",
    "andamento",
)

# Quelle per cui ZERO RIGHE VUOL DIRE CHE LA LETTURA E' ANDATA MALE, non che
# non c'e' niente da dire. Un listone vuoto e' fantacalcio.it che ha risposto
# 503, mai il campionato senza giocatori: si tiene quello di prima.
#
# LE ALTRE DEVONO POTER TORNARE VUOTE, e la distinzione non e' teorica. Gli
# squalificati sono nessuno per gran parte della stagione: trattare quel vuoto
# come un guasto vorrebbe dire non cancellare mai una squalifica scontata, e
# tenere un giocatore in panchina per sempre. La prima versione di questo file
# faceva esattamente questo.
MAI_VUOTE = ("giocatori", "statistiche", "calendario", "coppie", "campo")

# Chi punta a `giocatori`. Quando il listone cambia, le righe che parlano di
# un giocatore che non c'e' piu' non sono un problema da aggirare: sono
# informazioni su qualcuno che non gioca piu' in Serie A, e si buttano.
FIGLIE_DI_GIOCATORI = ("campo", "infortuni", "squalifiche")


@dataclass
class Esito:
    tabelle: dict[str, int]
    errore: str = ""

    @property
    def riuscito(self) -> bool:
        return not self.errore

    @property
    def righe(self) -> int:
        return sum(self.tabelle.values())


def tabelle_dello_schema(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    }


def esporta(conn: sqlite3.Connection, destinazione: Path | str) -> Esito:
    """Scrive un file con dentro le sole tabelle rileggibili.

    Si usa la copia integrale di SQLite e poi si SVUOTANO le tabelle che non
    devono viaggiare, invece di ricreare lo schema a mano: cosi' il file che
    parte ha esattamente lo schema di quello che arriva, migrazioni comprese,
    e non c'e' un secondo posto in cui tenere aggiornata la forma delle
    tabelle.
    """
    destinazione = Path(destinazione)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    if destinazione.exists():
        destinazione.unlink()

    fuori = sqlite3.connect(destinazione)
    try:
        conn.backup(fuori)
        presenti = tabelle_dello_schema(fuori)
        for tabella in MIE:
            if tabella in presenti:
                fuori.execute(f"DELETE FROM {tabella}")
        fuori.commit()
        fuori.execute("VACUUM")
        conte = {
            t: fuori.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in DI_RIFERIMENTO
            if t in presenti
        }
    finally:
        fuori.close()
    return Esito(tabelle=conte)


def assorbi(conn: sqlite3.Connection, sorgente: Path | str) -> Esito:
    """Sostituisce le tabelle rileggibili con quelle del file, e nient'altro.

    TUTTO O NIENTE. Se una tabella a meta' strada va storta, la transazione
    riporta indietro anche le precedenti: un listone nuovo accanto a minuti
    vecchi e' peggio di due dati vecchi che almeno si riferiscono allo stesso
    momento.
    """
    sorgente = Path(sorgente)
    if not sorgente.exists():
        return Esito(tabelle={}, errore=f"non trovo {sorgente.name}")

    conte: dict[str, int] = {}
    try:
        conn.execute("ATTACH DATABASE ? AS nuovo", (str(sorgente),))
    except sqlite3.Error as e:
        return Esito(tabelle={}, errore=f"non riesco ad aprire {sorgente.name}: {e}")
    try:
        arrivate = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM nuovo.sqlite_master WHERE type = 'table'"
            )
        }
        qui = tabelle_dello_schema(conn)
        # LE CHIAVI ESTERNE SI CONTROLLANO ALLA FINE, non riga per riga.
        # `campo`, `infortuni` e `squalifiche` puntano a `giocatori`: appena si
        # svuota il listone per rimetterlo nuovo, quelle righe restano appese
        # per un istante e SQLite rifiuta tutto — il sync non sarebbe mai
        # riuscito una volta sola su un database in uso. Si spengono qui, si
        # ripuliscono gli orfani, e si riaccendono per il controllo finale:
        # la coerenza si pretende dove deve esserci, cioe' alla fine.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        for tabella in DI_RIFERIMENTO:
            if tabella not in arrivate or tabella not in qui:
                continue
            quante = conn.execute(
                f"SELECT COUNT(*) FROM nuovo.{tabella}"
            ).fetchone()[0]
            if not quante and tabella in MAI_VUOTE:
                log.warning("%s arriva vuota: tengo quella di prima", tabella)
                continue
            conn.execute(f"DELETE FROM {tabella}")
            conn.execute(f"INSERT INTO {tabella} SELECT * FROM nuovo.{tabella}")
            conte[tabella] = quante

        if "giocatori" in conte:
            for figlia in FIGLIE_DI_GIOCATORI:
                if figlia in qui:
                    conn.execute(
                        f"DELETE FROM {figlia} WHERE id_fc NOT IN"
                        " (SELECT id_fc FROM giocatori)"
                    )

        orfane = conn.execute("PRAGMA foreign_key_check").fetchall()
        if orfane:
            conn.execute("ROLLBACK")
            return Esito(
                tabelle={},
                errore=(
                    f"{len(orfane)} righe resterebbero appese a giocatori che "
                    "non esistono: non ho assorbito niente"
                ),
            )
        conn.execute("COMMIT")
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        return Esito(tabelle={}, errore=f"non ho assorbito niente: {e}")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DETACH DATABASE nuovo")
    return Esito(tabelle=conte)
