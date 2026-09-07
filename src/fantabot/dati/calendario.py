"""Il calendario di Serie A, e quanto e' difficile ogni domenica.

PERCHE' SERVE. Gli abbinamenti di FantaLab dicono che due squadre si alternano
bene su trentotto giornate. Non dicono quale dei due portieri schierare
domenica prossima — e quella e' la domanda che si fa ogni settimana, mentre
l'altra si fa una volta sola all'asta. Il calendario e' il pezzo che le
collega: senza, l'abbinamento resta un numero da comprare e non una rotazione
da giocare.

COME SI CONTROLLA UNA TRASCRIZIONE. Un calendario ha una struttura cosi'
rigida che si verifica da sola, e le tre condizioni insieme non lasciano
passare quasi niente:

  · ogni giornata ha venti squadre, ognuna **una volta sola** — chi compare
    due volte o non compare e' un errore nella stessa riga;
  · ogni coppia ordinata (casa, ospite) esiste **esattamente una volta** in
    tutta la stagione: sono 20x19 = 380 partite, tante quante le righe;
  · le date non tornano mai indietro.

Non e' pedanteria: la prima trascrizione dal PDF aveva due partite sbagliate —
un `INTER vs MILAN` alla tredicesima e un `INTER vs COMO` alla trentasettesima,
tutti e due gia' presenti altrove. La regola degli accoppiamenti non si e'
limitata a segnalarle: avendo detto **quale** coppia mancava, ha detto anche
come andavano corrette.

DIFFICOLTA'. Quanto e' dura una partita non lo decide questo modulo: la forza
dei club la stima gia' il motore dai voti veri, ruolo per ruolo. Qui si legge
chi incontri e dove, e si somma il vantaggio di giocare in casa.
"""

from __future__ import annotations

import csv
import io
import itertools
import logging
import math
import sqlite3
from dataclasses import dataclass, field

from ..config import RADICE

log = logging.getLogger(__name__)

SEME = RADICE / "dati" / "calendario" / "serie-a-2026-27.csv"

GIORNATE = 38
SQUADRE_IN_SERIE_A = 20

# Quanto vale giocare in casa, in punti della stessa scala con cui il motore
# misura la forza dei club. E' il vantaggio piu' documentato del calcio e il
# piu' piccolo dei tre fattori che contano: sposta, non decide.
VANTAGGIO_CASA = 0.15


@dataclass(frozen=True)
class Partita:
    giornata: int
    casa: str
    ospite: str
    data: str = ""

    def avversario_di(self, sigla: str) -> str:
        return self.ospite if sigla == self.casa else self.casa

    def in_casa(self, sigla: str) -> bool:
        return sigla == self.casa


@dataclass
class Esito:
    partite: int = 0
    giornate: int = 0
    problemi: list[str] = field(default_factory=list)
    errore: str = ""

    @property
    def riuscito(self) -> bool:
        return not self.errore and self.partite > 0


def leggi_csv(testo: str) -> list[Partita]:
    """Le partite di un CSV `giornata,data,casa,ospite`, senza giudicarle."""
    partite: list[Partita] = []
    for riga in csv.DictReader(io.StringIO(testo)):
        pulita = {
            (k or "").strip().lower(): (v or "").strip() for k, v in riga.items()
        }
        try:
            giornata = int(pulita.get("giornata", ""))
        except ValueError:
            continue
        casa = pulita.get("casa", "").upper()
        ospite = pulita.get("ospite", "").upper()
        if not casa or not ospite or casa == ospite:
            continue
        partite.append(
            Partita(
                giornata=giornata,
                casa=casa,
                ospite=ospite,
                data=pulita.get("data", ""),
            )
        )
    return partite


def controlla(partite: list[Partita]) -> list[str]:
    """Le tre condizioni, in italiano leggibile.

    Restituisce l'elenco di cosa non torna. Vuoto vuol dire che il calendario
    e' fatto come un calendario, ed e' la sola prova che una trascrizione a
    mano puo' dare di se stessa.
    """
    problemi: list[str] = []
    if not partite:
        return ["nessuna partita riconosciuta"]

    squadre = sorted({p.casa for p in partite} | {p.ospite for p in partite})
    if len(squadre) != SQUADRE_IN_SERIE_A:
        problemi.append(f"{len(squadre)} squadre invece di {SQUADRE_IN_SERIE_A}")

    per_giornata: dict[int, list[Partita]] = {}
    for p in partite:
        per_giornata.setdefault(p.giornata, []).append(p)

    for giornata in sorted(per_giornata):
        elenco = per_giornata[giornata]
        presenze: dict[str, int] = {}
        for p in elenco:
            presenze[p.casa] = presenze.get(p.casa, 0) + 1
            presenze[p.ospite] = presenze.get(p.ospite, 0) + 1
        doppie = sorted(s for s, n in presenze.items() if n > 1)
        assenti = sorted(s for s in squadre if s not in presenze)
        if doppie or assenti:
            problemi.append(
                f"giornata {giornata}: "
                + (f"due volte {', '.join(doppie)}" if doppie else "")
                + ("; " if doppie and assenti else "")
                + (f"manca {', '.join(assenti)}" if assenti else "")
            )

    viste: dict[tuple[str, str], list[int]] = {}
    for p in partite:
        viste.setdefault((p.casa, p.ospite), []).append(p.giornata)
    for coppia, giornate in sorted(viste.items()):
        if len(giornate) > 1:
            problemi.append(
                f"{coppia[0]}-{coppia[1]} giocata due volte "
                f"(giornate {', '.join(str(g) for g in giornate)})"
            )
    if len(squadre) == SQUADRE_IN_SERIE_A:
        mai = [c for c in itertools.permutations(squadre, 2) if c not in viste]
        if mai:
            problemi.append(
                "mai in calendario: "
                + ", ".join(f"{a}-{b}" for a, b in mai[:8])
                + ("…" if len(mai) > 8 else "")
            )

    date = {p.giornata: p.data for p in partite if p.data}
    ordinate = sorted(date)
    indietro = [
        g for g, dopo in zip(ordinate, ordinate[1:], strict=False) if date[g] > date[dopo]
    ]
    if indietro:
        problemi.append(
            "date che tornano indietro dopo la giornata "
            + ", ".join(str(g) for g in indietro[:5])
        )
    return problemi


def salva(conn: sqlite3.Connection, partite: list[Partita]) -> None:
    conn.execute("DELETE FROM calendario")
    conn.executemany(
        "INSERT INTO calendario (giornata, data, casa, ospite) VALUES (?, ?, ?, ?)",
        [(p.giornata, p.data, p.casa, p.ospite) for p in partite],
    )
    conn.commit()


def importa(conn: sqlite3.Connection, testo: str) -> Esito:
    """Legge un calendario e lo salva, se e' fatto come un calendario.

    NON SI IMPORTA A META'. Un calendario con un buco fa dire al bot che una
    squadra riposa quando invece gioca, ed e' un consiglio peggiore del
    silenzio: chi non ha il dato lo sa, chi ha il dato sbagliato no.
    """
    esito = Esito()
    partite = leggi_csv(testo)
    esito.problemi = controlla(partite)
    if esito.problemi:
        esito.errore = "il calendario non torna: " + esito.problemi[0]
        return esito
    salva(conn, partite)
    esito.partite = len(partite)
    esito.giornate = len({p.giornata for p in partite})
    return esito


def carica_seme(conn: sqlite3.Connection) -> int:
    """Il calendario che il progetto porta con se', se non ce n'e' gia' uno."""
    gia = conn.execute("SELECT COUNT(*) FROM calendario").fetchone()[0]
    if gia or not SEME.exists():
        return 0
    esito = importa(conn, SEME.read_text(encoding="utf-8"))
    if not esito.riuscito:
        log.warning("calendario non caricato: %s", esito.errore)
        return 0
    return esito.partite


# -- leggere il calendario -------------------------------------------------


def partite_di(conn: sqlite3.Connection, giornata: int) -> list[Partita]:
    return [
        Partita(
            giornata=r["giornata"], casa=r["casa"], ospite=r["ospite"], data=r["data"]
        )
        for r in conn.execute(
            "SELECT giornata, data, casa, ospite FROM calendario"
            " WHERE giornata = ? ORDER BY casa",
            (giornata,),
        )
    ]


def per_squadra(conn: sqlite3.Connection, giornata: int) -> dict[str, Partita]:
    """La partita di ogni squadra in quella giornata, indicizzata per sigla."""
    trovate: dict[str, Partita] = {}
    for p in partite_di(conn, giornata):
        trovate[p.casa] = p
        trovate[p.ospite] = p
    return trovate


def giornate_note(conn: sqlite3.Connection) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT giornata FROM calendario ORDER BY giornata"
        )
    ]


def prossima_giornata(conn: sqlite3.Connection, oggi: str, da: int = 1) -> int:
    """La prima giornata non ancora giocata, o l'ultima se sono finite.

    Si guarda la data e non i risultati: il bot i risultati non li ha, e la
    domanda «che giornata si gioca adesso» ha comunque una sola risposta.
    """
    righe = conn.execute(
        "SELECT giornata, MIN(data) AS quando FROM calendario"
        " WHERE giornata >= ? GROUP BY giornata ORDER BY giornata",
        (da,),
    ).fetchall()
    if not righe:
        return da
    for r in righe:
        if not r["quando"] or r["quando"] >= oggi:
            return r["giornata"]
    return righe[-1]["giornata"]


def normalizza_forze(grezze: dict[str, float]) -> dict[str, float]:
    """Le forze dei club portate su una scala da -1 (la piu' debole) a +1.

    Il motore misura la forza come somma dei FVM della rosa: un numero in
    scala di mercato, che va da qualche centinaio a qualche migliaio e non si
    puo' sommare a una fantamedia. Qui si passa in scala logaritmica — da 300
    a 600 e' un salto, da 2400 a 2700 no — e poi si stira fra i due estremi
    della Serie A di quest'anno, che e' l'unico paragone che conta: la partita
    piu' dura possibile e' contro la piu' forte che c'e'.
    """
    if not grezze:
        return {}
    logaritmi = {
        club: math.log10(max(valore, 1.0)) for club, valore in grezze.items()
    }
    minimo, massimo = min(logaritmi.values()), max(logaritmi.values())
    meta = (massimo + minimo) / 2
    ampiezza = (massimo - minimo) / 2
    if ampiezza < 1e-9:
        return dict.fromkeys(logaritmi, 0.0)
    return {club: (x - meta) / ampiezza for club, x in logaritmi.items()}


def difficolta(partita: Partita, sigla: str, forze: dict[str, float]) -> float:
    """Quanto e' dura questa partita per questa squadra. Piu' alto = peggio.

    Due pezzi e basta: quanto vale l'avversario, e se si gioca in casa. La
    forza dei club non la inventa questo modulo — la stima il motore dai voti
    veri, che e' l'unico posto dove quel numero puo' nascere onesto. Le `forze`
    vanno gia' normalizzate: vedi `normalizza_forze`.
    """
    avversario = partita.avversario_di(sigla)
    durezza = forze.get(avversario, 0.0)
    return durezza - (VANTAGGIO_CASA if partita.in_casa(sigla) else -VANTAGGIO_CASA)
