"""Il database SQLite: schema, connessione, migrazioni.

Sqlite e non Postgres perche' questo bot serve una persona e deve poter girare
sul portatile la sera dell'asta senza che nulla sia "su". Lo schema e' creato
da migrazioni numerate — mai da un `create_all` implicito — cosi' aggiungere
una colonna a stagione iniziata non cancella la rosa.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import DB

# Ogni voce e' (numero, sql). Si aggiunge in fondo, non si modifica in mezzo.
MIGRAZIONI: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE giocatori (
            id_fc          INTEGER PRIMARY KEY,
            nome           TEXT NOT NULL,
            nome_cerca     TEXT NOT NULL,
            squadra        TEXT NOT NULL,
            ruolo          TEXT NOT NULL,
            ruolo_mantra   TEXT NOT NULL DEFAULT '',
            quota_iniziale INTEGER NOT NULL DEFAULT 1,
            quota_attuale  INTEGER NOT NULL DEFAULT 1,
            fvm            INTEGER NOT NULL DEFAULT 0,
            aggiornato_il  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_giocatori_ruolo ON giocatori(ruolo);
        CREATE INDEX idx_giocatori_cerca ON giocatori(nome_cerca);

        CREATE TABLE statistiche (
            id_fc         INTEGER NOT NULL,
            stagione      TEXT NOT NULL,
            squadra       TEXT NOT NULL DEFAULT '',
            presenze      INTEGER NOT NULL DEFAULT 0,
            media_voto    REAL NOT NULL DEFAULT 0,
            fantamedia    REAL NOT NULL DEFAULT 0,
            gol           INTEGER NOT NULL DEFAULT 0,
            gol_subiti    INTEGER NOT NULL DEFAULT 0,
            assist        INTEGER NOT NULL DEFAULT 0,
            ammonizioni   INTEGER NOT NULL DEFAULT 0,
            espulsioni    INTEGER NOT NULL DEFAULT 0,
            rigori_segnati  INTEGER NOT NULL DEFAULT 0,
            rigori_calciati INTEGER NOT NULL DEFAULT 0,
            rigori_parati   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id_fc, stagione)
        );

        CREATE TABLE leghe (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL UNIQUE,
            nome         TEXT NOT NULL DEFAULT 'La mia lega',
            crediti      INTEGER NOT NULL DEFAULT 500,
            n_squadre    INTEGER NOT NULL DEFAULT 8,
            slot_p       INTEGER NOT NULL DEFAULT 3,
            slot_d       INTEGER NOT NULL DEFAULT 8,
            slot_c       INTEGER NOT NULL DEFAULT 8,
            slot_a       INTEGER NOT NULL DEFAULT 6,
            prudenza     REAL NOT NULL DEFAULT 1.0,
            creata_il    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE squadre (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            id_lega  INTEGER NOT NULL REFERENCES leghe(id) ON DELETE CASCADE,
            nome     TEXT NOT NULL,
            e_mia    INTEGER NOT NULL DEFAULT 0,
            UNIQUE (id_lega, nome)
        );

        CREATE TABLE acquisti (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            id_lega    INTEGER NOT NULL REFERENCES leghe(id) ON DELETE CASCADE,
            id_fc      INTEGER NOT NULL,
            id_squadra INTEGER NOT NULL REFERENCES squadre(id) ON DELETE CASCADE,
            prezzo     INTEGER NOT NULL,
            creato_il  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (id_lega, id_fc)
        );
        CREATE INDEX idx_acquisti_lega ON acquisti(id_lega);

        CREATE TABLE preferenze (
            id_lega  INTEGER NOT NULL REFERENCES leghe(id) ON DELETE CASCADE,
            id_fc    INTEGER NOT NULL,
            grado    INTEGER NOT NULL DEFAULT 0,
            nota     TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (id_lega, id_fc)
        );
        """,
    ),
    (
        2,
        # Il modificatore di difesa cambia quali difensori conviene comprare,
        # e in molte leghe si decide la sera stessa: deve essere una riga da
        # cambiare in un secondo, non una versione diversa del bot.
        """
        ALTER TABLE leghe ADD COLUMN modificatore INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        3,
        # A buste chiuse il consiglio principale cambia numero: si offre il
        # proprio massimo, non la cifra che basta a superare gli altri.
        """
        ALTER TABLE leghe ADD COLUMN buste INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        4,
        # Quello che un tool esterno sa e il listone no: soprattutto a quanto
        # un giocatore viene pagato davvero nelle aste vere. E' il dato che il
        # motore puo' solo stimare, e vale piu' di qualunque stima.
        """
        CREATE TABLE mercato_esterno (
            id_fc         INTEGER PRIMARY KEY,
            prezzo_medio  REAL,
            prezzo_max    REAL,
            fascia        INTEGER,
            fonte         TEXT NOT NULL DEFAULT '',
            importato_il  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        5,
        # Due numeri diversi, e vanno tenuti separati: quanto viene pagato
        # davvero (PMA, che il motore usa) e quanto il tool consiglia di
        # spendere al massimo (che si mostra e basta).
        """
        ALTER TABLE mercato_esterno ADD COLUMN prezzo_consigliato REAL;
        """,
    ),
    (
        6,
        # Il listone e' una fotografia di agosto e non sa chi gioca a
        # settembre. Questa tabella e' la sola cosa che lo dice, e si
        # RISCRIVE INTERA a ogni lettura: non e' uno storico, e' lo stato di
        # oggi. Tenerne la cronologia inviterebbe a sommare due giornate
        # lette due volte.
        """
        CREATE TABLE campo (
            id_fc             INTEGER PRIMARY KEY REFERENCES giocatori(id_fc),
            minuti            INTEGER NOT NULL DEFAULT 0,
            presenze          INTEGER NOT NULL DEFAULT 0,
            giornate_squadra  INTEGER NOT NULL DEFAULT 0,
            voto_fotmob       REAL,
            previsto_titolare INTEGER,
            letto_il          TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        7,
        # Da quando si legge anche la stagione in corso, una riga di
        # statistiche non e' piu' per forza una stagione intera. Senza sapere
        # su quante giornate poggia, tre presenze a settembre sono
        # indistinguibili da tre presenze in un anno passato in infermeria —
        # e sono l'opposto.
        """
        ALTER TABLE statistiche ADD COLUMN giornate INTEGER NOT NULL DEFAULT 38;
        """,
    ),
    (
        8,
        # I minuti dicono che uno non gioca, non perche'. Le due ragioni —
        # riserva o infortunato — portano a due decisioni opposte all'asta, e
        # questa tabella e' l'unica cosa che le separa. Il TESTO si conserva
        # per intero accanto alla stima: "ipotizziamo un lungo stop" non e'
        # una data, e chi offre deve poter leggere la frase.
        """
        CREATE TABLE infortuni (
            id_fc          INTEGER PRIMARY KEY REFERENCES giocatori(id_fc),
            testo          TEXT NOT NULL DEFAULT '',
            giornate_fuori INTEGER NOT NULL DEFAULT 0,
            datato         INTEGER NOT NULL DEFAULT 0,
            letto_il       TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        9,
        # Di chi e' il turno di chiamare, e — se la lega gioca a reparti —
        # quale reparto e' in ballo. Sono due righe di stato e non un
        # dettaglio: chi ha finito un reparto smette di poter chiamare per
        # quel reparto, e sapere quando resti l'unico che quel reparto lo
        # cerca ancora vale piu' di qualunque stima, perche' da quel momento
        # il prezzo lo fai tu.
        """
        ALTER TABLE leghe ADD COLUMN turno INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE leghe ADD COLUMN reparto TEXT NOT NULL DEFAULT '';
        """,
    ),
    (
        10,
        # I tre giudizi da 1 a 5 dell'export FantaLab. Titolarita' e integrita'
        # parlano della stessa cosa da due lati — quanto giochera' e quanto
        # reggera' — e sono l'unica fonte che sa del mercato estivo prima che
        # i minuti lo dimostrino.
        """
        ALTER TABLE mercato_esterno ADD COLUMN titolarita INTEGER;
        ALTER TABLE mercato_esterno ADD COLUMN integrita INTEGER;
        ALTER TABLE mercato_esterno ADD COLUMN affidabilita INTEGER;
        """,
    ),
    (
        11,
        # UNA FOTOGRAFIA PER GIORNATA dei totali di stagione. Il sito pubblica
        # solo i cumulati — 5 gol, fantamedia 12,33 — e da un cumulato non si
        # ricava cosa e' successo domenica scorsa. Conservando la fotografia di
        # ogni giornata, la differenza fra due righe E' la giornata: bonus,
        # malus e minuti di quel turno, senza chiedere niente a nessuno.
        #
        # E' l'unica tabella che si accumula invece di essere riscritta, ed e'
        # per questo che la chiave e' (giocatore, giornata): rileggere due
        # volte la stessa giornata sovrascrive, non somma.
        """
        CREATE TABLE andamento (
            id_fc       INTEGER NOT NULL,
            giornata    INTEGER NOT NULL,
            presenze    INTEGER NOT NULL DEFAULT 0,
            media_voto  REAL NOT NULL DEFAULT 0,
            fantamedia  REAL NOT NULL DEFAULT 0,
            gol         INTEGER NOT NULL DEFAULT 0,
            assist      INTEGER NOT NULL DEFAULT 0,
            ammonizioni INTEGER NOT NULL DEFAULT 0,
            espulsioni  INTEGER NOT NULL DEFAULT 0,
            gol_subiti  INTEGER NOT NULL DEFAULT 0,
            minuti      INTEGER NOT NULL DEFAULT 0,
            letto_il    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (id_fc, giornata)
        );
        """,
    ),
    (
        12,
        # Le etichette che l'export mette accanto a ogni giocatore
        # ("rigorista", "rischio infortuni", "subentrante"): vocabolario
        # chiuso di sedici voci, tenute come testo separato da virgole perche'
        # servono soprattutto da leggere.
        """
        ALTER TABLE mercato_esterno ADD COLUMN note TEXT NOT NULL DEFAULT '';
        """,
    ),
    (
        13,
        # Quanto due squadre si abbinano bene, per i ruoli di cui se ne
        # schiera uno solo alla volta. La coppia si tiene UNA VOLTA SOLA, in
        # ordine alfabetico: Lecce-Napoli e Napoli-Lecce sono lo stesso
        # abbinamento, e tenerli due volte inviterebbe a leggerli come due.
        """
        CREATE TABLE coppie (
            ruolo     TEXT NOT NULL,
            sigla_a   TEXT NOT NULL,
            sigla_b   TEXT NOT NULL,
            punteggio INTEGER NOT NULL,
            fonte     TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (ruolo, sigla_a, sigla_b)
        );
        """,
    ),
    (
        14,
        # Il calendario, che e' la cosa che trasforma un abbinamento di
        # stagione in un consiglio di domenica. La chiave e' (giornata, casa)
        # e non (giornata, casa, ospite): una squadra gioca UNA partita per
        # giornata, e volerne due e' sempre un errore di trascrizione.
        """
        CREATE TABLE calendario (
            giornata INTEGER NOT NULL,
            data     TEXT NOT NULL DEFAULT '',
            casa     TEXT NOT NULL,
            ospite   TEXT NOT NULL,
            PRIMARY KEY (giornata, casa)
        );
        CREATE INDEX idx_calendario_ospite ON calendario(giornata, ospite);
        """,
    ),
    (
        15,
        # Da quale giornata comincia la TUA lega. Non e' sempre la prima: chi
        # fa l'asta a campionato gia' iniziato parte dalla quarta, e un bot
        # che gli parla della prima gli sta parlando di partite gia' giocate.
        """
        ALTER TABLE leghe ADD COLUMN prima_giornata INTEGER NOT NULL DEFAULT 1;
        """,
    ),
    (
        16,
        # Squalificati e diffidati. Si riscrive intera a ogni lettura, come gli
        # infortuni: e' lo stato di QUESTA settimana, e sommare due letture
        # terrebbe fuori un giocatore per il doppio del dovuto.
        """
        CREATE TABLE squalifiche (
            id_fc     INTEGER PRIMARY KEY REFERENCES giocatori(id_fc),
            giornate  INTEGER NOT NULL DEFAULT 0,
            diffidato INTEGER NOT NULL DEFAULT 0,
            testo     TEXT NOT NULL DEFAULT '',
            letto_il  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
)


def _applica_migrazioni(conn: sqlite3.Connection) -> None:
    versione = conn.execute("PRAGMA user_version").fetchone()[0]
    for numero, sql in MIGRAZIONI:
        if numero <= versione:
            continue
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {numero}")
        conn.commit()


def connetti(percorso: Path | str | None = None) -> sqlite3.Connection:
    """Apre il database, creandolo e migrandolo se serve."""
    percorso = Path(percorso) if percorso is not None else DB
    if percorso != Path(":memory:"):
        percorso.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(percorso, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _applica_migrazioni(conn)
    return conn


@contextmanager
def transazione(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Tutto o niente: un'assegnazione d'asta non puo' restare a meta'."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
