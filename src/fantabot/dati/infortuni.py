"""Chi e' fermo, per cosa, e fino a quando.

PERCHE' ESISTE, ED E' DIVERSO DA `campo.py`. I minuti dicono che un giocatore
non gioca. Non dicono **perche'**, e le due ragioni possibili portano a due
decisioni opposte all'asta:

  · e' una riserva — allora vale poco, e vale poco anche a marzo;
  · e' infortunato — allora vale quello che vale, meno le giornate che salta,
    e se il mercato lo ha gia' scaricato e' l'occasione migliore del tavolo.

Il 6 settembre 2026 Yildiz aveva 69 minuti su 180 e il bot lo consigliava a 31
crediti. La ragione dei 69 minuti era una frattura del quinto metatarso
operata il 31 agosto, con rientro previsto da fine novembre: dodici giornate.
Nessun dato sui minuti poteva dirlo, e nessuna formazione prevista nemmeno —
un infortunato di lungo corso non compare in nessuna delle due parti.

Al contrario, Buongiorno ha zero minuti e rientra a meta' novembre: senza
questa pagina il bot lo tratta come la quarta scelta del Napoli, mentre e' il
suo centrale titolare.

LA FONTE e' `fantacalcio.it/infortunati-serie-a`, pubblica e senza login, e ha
il pregio decisivo di scrivere i nomi **nella stessa forma del listone**
("Sarr P.", "El Azzouzi O.", "Esposito F.P."): l'aggancio non ha bisogno di
nessuna somiglianza, e quindi non puo' sbagliare persona.

I TEMPI DI RIENTRO SONO PROSA, e vanno trattati come tali. Qui si estrae un
numero di giornate perche' il motore ha bisogno di un numero, ma **il testo
originale si conserva e si mostra sempre**: "ipotizziamo un lungo stop" non e'
una data, e chi offre deve poter leggere la frase invece della sua
approssimazione.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date

import httpx
from bs4 import BeautifulSoup

from .aggiorna import normalizza

log = logging.getLogger(__name__)

PAGINA = "https://www.fantacalcio.it/infortunati-serie-a"

# Come questa pagina scrive i club. Diciannove su venti coincidono con il resto
# del sito; "Inter" e' l'unico accorciato.
SQUADRE: dict[str, str] = {
    "atalanta": "ATA",
    "bologna": "BOL",
    "cagliari": "CAG",
    "como": "COM",
    "fiorentina": "FIO",
    "frosinone": "FRO",
    "genoa": "GEN",
    "inter": "INT",
    "juventus": "JUV",
    "lazio": "LAZ",
    "lecce": "LEC",
    "milan": "MIL",
    "monza": "MON",
    "napoli": "NAP",
    "parma": "PAR",
    "roma": "ROM",
    "sassuolo": "SAS",
    "torino": "TOR",
    "udinese": "UDI",
    "venezia": "VEN",
}

MESI = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

# Una giornata a settimana: e' il ritmo della Serie A, turni infrasettimanali
# a parte. Basta per trasformare "fine novembre" in un numero di partite.
GIORNI_PER_GIORNATA = 7

# Dove cade nel mese, secondo come lo scrivono. "Seconda meta'" va cercata
# prima di "meta'", altrimenti la seconda vince sempre sulla prima.
QUANDO_NEL_MESE: tuple[tuple[str, int], ...] = (
    ("seconda meta", 20),
    ("prima meta", 10),
    ("inizio", 5),
    ("meta", 15),
    ("fine", 27),
)
GIORNO_SENZA_QUALIFICA = 10

# Le parole con cui la pagina annuncia un rientro. Servono ad ancorare la
# lettura: solo un mese che viene DOPO una di queste e' una data di rientro,
# tutti gli altri sono la cronaca dell'infortunio.
RIENTRO = (
    "rientr",
    "recuper",
    "torn",
    "ritorno",
    "arruolabile",
    "convocabile",
    "disposizione",
    "riaverlo",
    "in campo",
    # "da valutare IN VISTA della 4a giornata" e "lo terra' ai box FINO ALLA
    # prima meta' di ottobre": due modi di dire un rientro senza usare la
    # parola, ed erano gli unici due casi rimasti senza data.
    "in vista",
    "fino a",
)

# La giornata nominata: "dalla 4a giornata", "rientro dalla 4a di campionato".
# Ancorata a "giornata" o "campionato" perche' da sola una cifra seguita da
# "a" ricorre anche altrove.
GIORNATA_NOMINATA = re.compile(r"\b(\d{1,2})\s*a\s+(?:giornata|di campionato)")
# "assente nel prossimo turno": una giornata, senza numeri da leggere.
PROSSIMO_TURNO = ("prossimo turno", "prossima giornata")

# Una durata al posto di una data: "stop di almeno due mesi", "circa 25
# giorni". Meno precisa di un mese nominato — non dice da quando si conta — ma
# infinitamente meglio del "da valutare" che sarebbe l'alternativa.
NUMERI = {
    "un": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
}
DURATA = re.compile(
    r"\b(\d{1,3}|" + "|".join(NUMERI) + r")\s+(mes\w*|settiman\w*|giorn\w*)\b"
)
GIORNATE_PER_UNITA = {
    "m": 30.0 / GIORNI_PER_GIORNATA,
    "s": 1.0,
    "g": 1.0 / GIORNI_PER_GIORNATA,
}


# Quando il testo non da' nessuna data ma nomina un infortunio di quelli che
# si misurano in mesi. Questi tre non sono un elenco di medicina: sono le
# parole che comparivano nelle sette schede senza data del 6 settembre 2026,
# tutte di gente ferma da mesi.
LUNGHI = ("crociato", "achille", "lungo stop", "tendine rotuleo")
GIORNATE_SE_LUNGO = 20

# Quando il testo dice solo "da valutare". Non e' zero — una scheda esiste
# perche' qualcosa c'e' — ed e' l'unico numero che si puo' dire senza inventare.
GIORNATE_SE_DA_VALUTARE = 1

GIORNATE_STAGIONE = 38


@dataclass(frozen=True)
class Infortunio:
    id_fc: int
    nome: str
    squadra: str
    testo: str
    # Le giornate che verosimilmente salta ancora, da adesso.
    giornate_fuori: int
    # Vero quando il numero viene da una data o da una giornata scritte nel
    # testo; falso quando e' una stima nostra su parole come "lungo stop".
    datato: bool

    @property
    def lungo(self) -> bool:
        return self.giornate_fuori >= 6


# --------------------------------------------------------------- il testo


def dove_si_parla_di_rientro(piatto: str) -> int | None:
    """Da dove in poi il testo parla del ritorno invece che dell'infortunio."""
    return min(
        (m.start() for parola in RIENTRO for m in re.finditer(parola, piatto)),
        default=None,
    )


def _mese_indicato(testo: str, oggi: date) -> date | None:
    """La data di RIENTRO nominata nel testo, se c'e'.

    IL MESE DA SOLO NON VUOL DIRE NIENTE, e questa e' la parte che sbaglia se
    la si scrive in fretta. Ogni scheda nomina almeno due mesi, e quello che si
    legge per primo e' quasi sempre quello dell'infortunio:

        «dopo la gara di Frosinone (23 agosto) ... Operato il 31 agosto ...
         Ipotesi di rientro in campo da fine novembre»

    Prendere il primo mese trovato dava ad agosto il ruolo di data di rientro,
    e siccome agosto e' passato finiva nell'agosto dell'anno dopo: Yildiz
    risultava fuori per tutta la stagione invece che per dodici giornate.

    Il mese giusto e' quello che viene DOPO una parola di rientro. Si cerca
    quindi la parola, e poi il primo mese alla sua destra.
    """
    piatto = normalizza(testo)
    inizio = dove_si_parla_di_rientro(piatto)
    if inizio is None:
        return None

    trovati = [
        (piatto.find(nome, inizio), nome, numero)
        for nome, numero in MESI.items()
        if piatto.find(nome, inizio) >= 0
    ]
    if not trovati:
        return None
    dove, _, numero = min(trovati)

    prima = piatto[max(inizio, dove - 22) : dove]
    giorno = GIORNO_SENZA_QUALIFICA
    for parola, quando in QUANDO_NEL_MESE:
        if parola in prima:
            giorno = quando
            break
    # Un mese gia' passato e' l'anno prossimo: "gennaio" letto a settembre non
    # e' il gennaio scorso. Il campionato scavalca il capodanno, e senza questa
    # riga un rientro a gennaio risulterebbe otto mesi fa.
    anno = oggi.year + 1 if numero < oggi.month else oggi.year
    return date(anno, numero, giorno)


def giornate_fuori(testo: str, *, giornata: int, oggi: date | None = None) -> tuple[int, bool]:
    """Quante giornate salta ancora, e se il numero e' scritto o stimato.

    Tre letture, in ordine di quanto sono affidabili:

      1. **la giornata nominata** ("rientro dalla 4a di campionato"), che e'
         gia' l'unita' che serve e non ha bisogno di conversioni;
      2. **il mese** ("da fine novembre"), che diventa giornate a una alla
         settimana;
      3. **le parole**, quando non c'e' ne' l'una ne' l'altro: un crociato non
         ha una data e non per questo dura poco.
    """
    oggi = oggi or date.today()
    piatto = normalizza(testo)

    # ANCHE LA GIORNATA VA ANCORATA AL RIENTRO, per la stessa ragione del
    # mese: «out nella 3a di campionato contro l'Udinese» nomina la giornata
    # che salta, non quella in cui torna, e presa per buona diceva che Patric
    # rientrava ieri. Deve venire dopo una parola di ritorno.
    inizio = dove_si_parla_di_rientro(piatto)
    quando = GIORNATA_NOMINATA.search(piatto, inizio) if inizio is not None else None
    if quando is not None:
        # Rientra PER quella giornata: quelle che salta sono quelle in mezzo.
        return max(0, int(quando.group(1)) - giornata - 1), True

    rientro = _mese_indicato(testo, oggi)
    if rientro is not None:
        giorni = (rientro - oggi).days
        return max(0, round(giorni / GIORNI_PER_GIORNATA)), True

    quanto = DURATA.search(piatto)
    if quanto is not None:
        numero = quanto.group(1)
        quante = float(numero) if numero.isdigit() else NUMERI[numero]
        # La durata si conta dall'infortunio, che e' gia' cominciato: quanto
        # resta e' meno di quanto e' scritto, e non sappiamo quanto meno.
        # Falso su `datato` apposta: e' una stima, non una data.
        return round(quante * GIORNATE_PER_UNITA[quanto.group(2)[0]]), False

    if any(p in piatto for p in LUNGHI):
        return GIORNATE_SE_LUNGO, False
    if any(p in piatto for p in PROSSIMO_TURNO):
        return 1, True
    return GIORNATE_SE_DA_VALUTARE, False


# --------------------------------------------------------------- la pagina


def _scarica(client: httpx.Client) -> str:
    risposta = client.get(
        PAGINA,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
            )
        },
    )
    risposta.raise_for_status()
    return risposta.text


def analizza(
    html: str, listone: dict[tuple[str, str], int], *, giornata: int, oggi: date | None = None
) -> list[Infortunio]:
    """Le schede della pagina, agganciate al listone per squadra e nome.

    `listone` e' {(sigla, nome normalizzato): id}. L'aggancio e' esatto e non
    perdona: questa pagina scrive i nomi come il listone perche' e' lo stesso
    sito, e una somiglianza qui servirebbe solo a sbagliare persona.
    """
    zuppa = BeautifulSoup(html, "lxml")
    esito: list[Infortunio] = []
    for scheda in zuppa.select(".team-card"):
        etichetta = scheda.select_one(".team-name")
        sigla = (
            SQUADRE.get(normalizza(etichetta.get_text(" ", strip=True)))
            if etichetta
            else None
        )
        if sigla is None:
            continue
        for voce in scheda.select("li"):
            nome_el = voce.select_one(".item-name")
            if nome_el is None:
                continue
            nome = nome_el.get_text(" ", strip=True)
            descrizione = voce.select_one(".item-description")
            testo = descrizione.get_text(" ", strip=True) if descrizione else ""
            id_fc = listone.get((sigla, normalizza(nome)))
            if id_fc is None:
                # Capita: la pagina elenca anche chi il listone non quota.
                log.info("infortunato non nel listone: %s (%s)", nome, sigla)
                continue
            quante, datato = giornate_fuori(testo, giornata=giornata, oggi=oggi)
            esito.append(
                Infortunio(
                    id_fc=id_fc,
                    nome=nome,
                    squadra=sigla,
                    testo=testo,
                    giornate_fuori=min(quante, GIORNATE_STAGIONE),
                    datato=datato,
                )
            )
    return esito


# --------------------------------------------------------------- persistenza


def salva(conn: sqlite3.Connection, elenco: list[Infortunio]) -> None:
    """Sostituisce la fotografia precedente: chi guarisce sparisce."""
    conn.execute("DELETE FROM infortuni")
    conn.executemany(
        """
        INSERT INTO infortuni (id_fc, testo, giornate_fuori, datato)
        VALUES (?, ?, ?, ?)
        """,
        [(i.id_fc, i.testo, i.giornate_fuori, int(i.datato)) for i in elenco],
    )
    conn.commit()


def leggi(conn: sqlite3.Connection) -> dict[int, Infortunio]:
    esito: dict[int, Infortunio] = {}
    for r in conn.execute(
        "SELECT i.*, g.nome, g.squadra FROM infortuni i JOIN giocatori g ON g.id_fc = i.id_fc"
    ):
        esito[r["id_fc"]] = Infortunio(
            id_fc=r["id_fc"],
            nome=r["nome"],
            squadra=r["squadra"],
            testo=r["testo"],
            giornate_fuori=r["giornate_fuori"],
            datato=bool(r["datato"]),
        )
    return esito


def aggiorna(
    conn: sqlite3.Connection,
    client: httpx.Client | None = None,
    *,
    oggi: date | None = None,
) -> dict[str, int]:
    """Rilegge la pagina e riscrive la tabella."""
    proprio = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        html = _scarica(client)
    except httpx.HTTPError as e:
        log.warning("infortunati non letti: %s", e)
        return {"fermi": 0, "lunghi": 0}
    finally:
        if proprio:
            client.close()

    listone = {
        (r["squadra"], r["nome_cerca"]): r["id_fc"]
        for r in conn.execute("SELECT id_fc, nome_cerca, squadra FROM giocatori")
    }
    # La giornata in corso la sa gia' `campo`, che l'ha contata dalle rose:
    # chiederla a una terza fonte per un numero che e' in casa sarebbe una
    # cosa in piu' che si puo' rompere.
    riga = conn.execute("SELECT MAX(giornate_squadra) FROM campo").fetchone()
    giornata = (riga[0] if riga else 0) or 0

    elenco = analizza(html, listone, giornata=giornata, oggi=oggi)
    salva(conn, elenco)
    return {
        "fermi": len(elenco),
        "lunghi": sum(1 for i in elenco if i.lungo),
    }
