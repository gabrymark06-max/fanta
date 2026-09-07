"""Importa un foglio esportato da un altro tool d'asta (FantaLab e simili).

Il dato che vale di piu' e' uno solo: **a quanto quel giocatore viene pagato
davvero nelle aste**. Il motore di questo bot il prezzo lo puo' solo stimare
dal FVM; un tool che raccoglie migliaia di aste vere lo *sa*. Quando c'e', il
dato osservato vince sulla stima, e resta al bot il mestiere che il dato non
fa: dire quanto vale per te, chi te lo puo' contendere e quanto ti resta.

Il file non viene letto assumendo un formato. Le intestazioni si riconoscono
dalle parole che contengono, i nomi si abbinano al listone come farebbe la
ricerca del bot, e alla fine l'importazione **dichiara cosa ha capito**: quali
colonne ha usato, quanti giocatori ha riconosciuto e quali no. Un import che
sbaglia in silenzio la sera dell'asta e' peggio di un import che non parte.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from ..db import transazione
from .aggiorna import normalizza

# Come si riconosce una colonna: per le parole che ha nel titolo. L'ordine
# conta, la prima famiglia che combacia vince.
COLONNE = {
    "nome": ("nome", "giocatore", "calciatore", "player"),
    "squadra": ("squadra", "team", "club"),
    "ruolo": ("ruolo", "role", "pos"),
    # Quanto viene pagato DAVVERO nelle aste. Su FantaLab e' "PMA", espresso
    # come quota del budget di una squadra: la somma su tutto il listone fa
    # circa 100% per squadra, ed e' la verifica che dice se la colonna e'
    # quella giusta. E' il dato che vince su ogni stima.
    "prezzo_medio": (
        "pma",
        "prezzo medio",
        "media pagato",
        "pagato medio",
        "media asta",
        "prezzo asta",
        "costo medio",
        "media leghe",
    ),
    # Quanto il tool consiglia di spendere: un'opinione, non un'osservazione.
    # Si mostra accanto, non sostituisce il dato osservato.
    "prezzo_consigliato": ("prezzo consigliato", "prezzo", "costo"),
    "prezzo_max": ("prezzo max", "massimo", "tetto", "limite"),
    "fascia": ("fascia", "band", "tier"),
    "obiettivo": ("obiett", "target", "voglio"),
    # I TRE GIUDIZI DA 1 A 5 di FantaLab. Sono la cosa che il motore stimava
    # con piu' fatica, detta da chi il campionato lo guarda:
    #
    #   · TITOLARITA' - quanto giochera'. E' esattamente la quantita' che il
    #     bot ricava dal FVM e dallo storico, e questa versione sa gia' del
    #     mercato estivo e della gerarchia decisa in ritiro;
    #   · INTEGRITA'  - quanto regge. Un 2 vuol dire che si fara' male, e nei
    #     minuti giocati non si vede finche' non e' successo;
    #   · AFFIDABILITA' - quanto e' costante. Non sposta le presenze: sposta
    #     quanto fidarsi della fantamedia stimata.
    "titolarita": ("titolarit", "titolare"),
    "integrita": ("integrit",),
    "affidabilita": ("affidabilit",),
}

# Le etichette a parole, in colonne che si chiamano "Nota 1".."Nota 5" e
# "Commento". Non stanno in COLONNE perche' sono PIU' di una colonna sola e
# si raccolgono tutte insieme.
COLONNE_NOTE = ("nota", "commento")
# Parole che squalificano una colonna per quel campo, anche se il resto
# combacia: senza, "Prezzo max" verrebbe scambiato per il prezzo medio.
ESCLUSIONI = {
    "prezzo_medio": ("max", "massim", "min", "tetto"),
    "prezzo_consigliato": ("max", "massim", "medio", "media"),
    "squadra": ("mia", "my"),
}

# FantaLab scrive le fasce a parole. Si traducono in numeri perche' il resto
# del bot ragiona per fasce numeriche, dal top al fondo del listone.
FASCE_A_PAROLE = {
    "top": 1,
    "semi-top": 2,
    "semitop": 2,
    "seconda": 2,
    "terza": 3,
    "quarta": 4,
    "titolare": 4,
    "outsider": 5,
    "scomm": 5,
    "quinta": 5,
}
# Le colonne senza le quali non si combina niente.
INDISPENSABILI = ("nome",)


@dataclass
class Esito:
    """Cosa e' successo davvero, in una forma che si puo' raccontare."""

    colonne_usate: dict[str, str] = field(default_factory=dict)
    righe_lette: int = 0
    abbinati: int = 0
    con_prezzo: int = 0
    con_consigliato: int = 0
    con_fascia: int = 0
    con_giudizi: int = 0
    non_trovati: list[str] = field(default_factory=list)
    obiettivi: list[int] = field(default_factory=list)
    errore: str = ""

    @property
    def riuscito(self) -> bool:
        return not self.errore and self.abbinati > 0


def _pulisci(testo: object) -> str:
    piatto = unicodedata.normalize("NFKD", str(testo or ""))
    return "".join(c for c in piatto if not unicodedata.combining(c)).strip().lower()


def _riconosci_colonne(intestazioni: list[str]) -> dict[str, str]:
    """Associa ogni campo che ci serve alla colonna del file che lo contiene."""
    trovate: dict[str, str] = {}
    puliti = [_pulisci(i) for i in intestazioni]
    for campo, parole in COLONNE.items():
        vietate = ESCLUSIONI.get(campo, ())
        for parola in parole:
            for originale, pulito in zip(intestazioni, puliti, strict=True):
                if not pulito or originale in trovate.values():
                    continue
                if any(v in pulito for v in vietate):
                    continue
                if parola in pulito:
                    trovate[campo] = originale
                    break
            if campo in trovate:
                break
    return trovate


def _voto_1_5(riga: list, indice: int | None) -> int | None:
    """Un giudizio da 1 a 5, o niente.

    Fuori da quell'intervallo si scarta invece di troncare: una colonna che
    contiene 87 non e' una titolarita' con un refuso, e' un'altra colonna.
    """
    if indice is None or indice >= len(riga):
        return None
    grezzo = str(riga[indice] or "").strip().replace(",", ".")
    try:
        numero = round(float(grezzo))
    except ValueError:
        return None
    return numero if 1 <= numero <= 5 else None


def _fascia_da_testo(valore: object) -> int | None:
    """Una fascia puo' essere un numero o una parola: qui diventa un numero."""
    numero = _numero(valore)
    if numero and 1 <= numero <= 9:
        return int(numero)
    testo = _pulisci(valore)
    if not testo or "non impostata" in testo:
        return None
    # Dalla parola piu' lunga alla piu' corta: "semi-top" contiene "top", e
    # cercando prima "top" ogni semi-top diventava un top.
    for parola, livello in sorted(
        FASCE_A_PAROLE.items(), key=lambda voce: -len(voce[0])
    ):
        if parola in testo:
            return livello
    return None


def _numero(valore: object) -> float | None:
    grezzo = str(valore or "").strip().replace(",", ".")
    if not grezzo:
        return None
    ripulito = "".join(c for c in grezzo if c.isdigit() or c in ".-")
    try:
        numero = float(ripulito)
    except ValueError:
        return None
    return numero if numero > 0 else None


def _cella(riga: list[object], indice: int | None) -> float | None:
    """Il numero in quella colonna, se la colonna c'e' ed e' un numero."""
    if indice is None or indice >= len(riga):
        return None
    return _numero(riga[indice])


def leggi_tabella(dati: bytes, nome_file: str) -> tuple[list[str], list[list[object]]]:
    """Legge xlsx o csv e restituisce (intestazioni, righe).

    L'intestazione non e' sempre la prima riga: i fogli esportati spesso hanno
    un titolo o una riga vuota sopra. Si prende la prima riga che contiene una
    parola riconoscibile.
    """
    if nome_file.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        # Tutti i fogli, non solo il primo: FantaLab esporta un foglio per
        # ruolo, e leggerne uno solo avrebbe importato i portieri e basta.
        libro = load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
        righe = []
        for foglio in libro.worksheets:
            righe.extend(list(r) for r in foglio.iter_rows(values_only=True))
    else:
        testo = dati.decode("utf-8-sig", errors="replace")
        separatore = ";" if testo.count(";") > testo.count(",") else ","
        righe = [r for r in csv.reader(io.StringIO(testo), delimiter=separatore)]

    for indice, riga in enumerate(righe[:15]):
        intestazioni = [str(c or "").strip() for c in riga]
        if _riconosci_colonne(intestazioni).keys() & set(INDISPENSABILI):
            return intestazioni, righe[indice + 1 :]
    return ([str(c or "").strip() for c in righe[0]], righe[1:]) if righe else ([], [])


def importa(
    conn: sqlite3.Connection, dati: bytes, nome_file: str, fonte: str = "fantalab"
) -> Esito:
    """Legge il foglio e salva quello che ha riconosciuto."""
    esito = Esito()
    try:
        intestazioni, righe = leggi_tabella(dati, nome_file)
    except Exception as errore:
        esito.errore = f"non riesco ad aprire il file: {errore}"
        return esito
    if not intestazioni:
        esito.errore = "il file sembra vuoto"
        return esito

    colonne = _riconosci_colonne(intestazioni)
    esito.colonne_usate = colonne
    if "nome" not in colonne:
        esito.errore = (
            "non trovo una colonna con i nomi dei giocatori. "
            f"Le intestazioni che ho letto sono: {', '.join(intestazioni[:8])}"
        )
        return esito
    if not {
        "prezzo_medio",
        "prezzo_consigliato",
        "prezzo_max",
        "fascia",
    } & colonne.keys():
        esito.errore = (
            "trovo i nomi ma nessuna colonna con prezzi o fasce: "
            "cosi' non c'e' niente da aggiungere a quello che gia' so."
        )
        return esito

    indici = {campo: intestazioni.index(col) for campo, col in colonne.items()}
    indici_note = [
        i
        for i, testa in enumerate(intestazioni)
        if _pulisci(testa).startswith(COLONNE_NOTE)
    ]
    listone = {
        r["nome_cerca"]: (r["id_fc"], r["squadra"])
        for r in conn.execute("SELECT id_fc, nome_cerca, squadra FROM giocatori")
    }

    da_salvare: list[tuple] = []
    for riga in righe:
        if not riga or indici["nome"] >= len(riga):
            continue
        nome = str(riga[indici["nome"]] or "").strip()
        if not nome:
            continue
        # Un export a piu' fogli ripete l'intestazione a ogni foglio: quella
        # riga non e' un giocatore che non ho riconosciuto, e' una riga di
        # titolo, e va saltata senza finire fra gli scarti.
        if _pulisci(nome) in {_pulisci(i) for i in intestazioni}:
            continue
        esito.righe_lette += 1
        indice_squadra = indici.get("squadra")
        squadra = (
            str(riga[indice_squadra] or "")
            if indice_squadra is not None and indice_squadra < len(riga)
            else ""
        )
        id_fc = _abbina(nome, squadra, listone)
        if id_fc is None:
            if len(esito.non_trovati) < 12:
                esito.non_trovati.append(nome)
            continue
        esito.abbinati += 1

        note = ", ".join(
            testo
            for i in indici_note
            if i < len(riga) and (testo := str(riga[i] or "").strip())
        )
        titolarita = _voto_1_5(riga, indici.get("titolarita"))
        integrita = _voto_1_5(riga, indici.get("integrita"))
        affidabilita = _voto_1_5(riga, indici.get("affidabilita"))
        prezzo_medio = _cella(riga, indici.get("prezzo_medio"))
        prezzo_max = _cella(riga, indici.get("prezzo_max"))
        consigliato = _cella(riga, indici.get("prezzo_consigliato"))
        indice_fascia = indici.get("fascia")
        fascia = (
            _fascia_da_testo(riga[indice_fascia])
            if indice_fascia is not None and indice_fascia < len(riga)
            else None
        )
        indice_obiettivo = indici.get("obiettivo")
        obiettivo = bool(
            indice_obiettivo is not None
            and indice_obiettivo < len(riga)
            and str(riga[indice_obiettivo] or "").strip()
        )
        if prezzo_medio:
            esito.con_prezzo += 1
        if consigliato:
            esito.con_consigliato += 1
        if fascia:
            esito.con_fascia += 1
        if obiettivo:
            esito.obiettivi.append(id_fc)
        if titolarita:
            esito.con_giudizi += 1
        da_salvare.append(
            (
                id_fc, prezzo_medio, prezzo_max, fascia, fonte, consigliato,
                titolarita, integrita, affidabilita, note,
            )
        )

    if not da_salvare:
        esito.errore = (
            "nessun nome del file corrisponde al listone. "
            "Hai lanciato /aggiorna almeno una volta?"
        )
        return esito

    with transazione(conn):
        conn.executemany(
            """
            INSERT INTO mercato_esterno
                (id_fc, prezzo_medio, prezzo_max, fascia, fonte,
                 prezzo_consigliato, titolarita, integrita, affidabilita,
                 note, importato_il)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id_fc) DO UPDATE SET
                prezzo_medio = coalesce(excluded.prezzo_medio, prezzo_medio),
                prezzo_max = coalesce(excluded.prezzo_max, prezzo_max),
                prezzo_consigliato = coalesce(
                    excluded.prezzo_consigliato, prezzo_consigliato),
                fascia = coalesce(excluded.fascia, fascia),
                titolarita = coalesce(excluded.titolarita, titolarita),
                integrita = coalesce(excluded.integrita, integrita),
                affidabilita = coalesce(excluded.affidabilita, affidabilita),
                note = excluded.note,
                fonte = excluded.fonte,
                importato_il = datetime('now')
            """,
            da_salvare,
        )
    return esito


def _abbina(nome: str, squadra: str, listone: dict[str, tuple[int, str]]) -> int | None:
    """Trova l'id del giocatore, perdonando le differenze di scrittura.

    Ogni tool scrive i nomi a modo suo - "Martinez L.", "Lautaro Martinez",
    "MARTINEZ LAUTARO". Si prova la forma esatta, poi il prefisso, e la
    squadra fa da giudice quando due nomi si somigliano.
    """
    chiave = normalizza(nome)
    if chiave in listone:
        return listone[chiave][0]

    squadra = squadra.strip().upper()[:3]
    candidati = [
        (k, v)
        for k, v in listone.items()
        if k.startswith(chiave) or chiave.startswith(k)
    ]
    if not candidati:
        # "Lautaro Martinez" contro "Martinez L.": si prova per cognome.
        pezzi = chiave.split()
        if len(pezzi) >= 2:
            candidati = [
                (k, v)
                for k, v in listone.items()
                if any(k.startswith(p) for p in pezzi if len(p) > 3)
            ]
    if not candidati:
        return None
    if squadra:
        con_squadra = [(k, v) for k, v in candidati if v[1] == squadra]
        if con_squadra:
            candidati = con_squadra
    if len(candidati) == 1 or squadra:
        return candidati[0][1][0]
    return None


def prezzi_esterni(conn: sqlite3.Connection) -> dict[int, float]:
    """I prezzi medi importati, per chi ce li ha."""
    return {
        r["id_fc"]: r["prezzo"]
        for r in conn.execute(
            """
            SELECT id_fc, coalesce(prezzo_medio, prezzo_consigliato) AS prezzo
            FROM mercato_esterno
            WHERE coalesce(prezzo_medio, prezzo_consigliato) > 0
            """
        )
    }


def riassunto(conn: sqlite3.Connection) -> dict[str, object]:
    r = conn.execute(
        """
        SELECT count(*) AS righe,
               count(prezzo_medio) AS prezzi,
               count(fascia) AS fasce,
               max(fonte) AS fonte,
               max(importato_il) AS quando
        FROM mercato_esterno
        """
    ).fetchone()
    return dict(r) if r else {}
