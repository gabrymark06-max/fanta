"""Leggere le regole della lega come le scrive una persona di fretta.

Le regole di una lega spesso si decidono il giorno stesso, dieci minuti prima
di cominciare, e chi le scrive al bot le ha appena sentite dire a voce. Deve
funzionare tutto: <code>500 8 3-8-8-6</code>, ma anche <code>10 squadre, 750
crediti, rose da 25, con modificatore</code>.

Nessuna posizione fissa, quindi: ogni numero viene riconosciuto da cosa gli
sta intorno, e da quanto e' grande. I crediti sono un numero grande, le
squadre un numero piccolo, la rosa quattro numeri attaccati da trattini. Se
manca qualcosa restano i valori di prima, che e' l'unico modo per poter
correggere un solo dettaglio senza riscrivere tutta la riga.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..motore.valutazione import RUOLI

# Le forme in cui la rosa viene scritta: 3-8-8-6, 3/8/8/6, 3 8 8 6.
ROSA = re.compile(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\b")
NUMERO_CON_PAROLA = re.compile(
    r"(\d{1,5})\s*(crediti|credit|budget|squadre|squadra|partecipanti|giocatori|"
    r"allenatori|fantallenatori)|"
    r"(crediti|credit|budget|squadre|squadra|partecipanti|allenatori|"
    r"fantallenatori)\s*(?:di|da|:)?\s*(\d{1,5})",
    re.IGNORECASE,
)
# Da che giornata comincia la lega: "dalla 4a giornata", "si parte dalla
# quarta", "giornata 4". Si cerca PER PRIMA e si toglie dal testo, perche'
# altrimenti quel 4 verrebbe letto come il numero di squadre — che e'
# esattamente il tipo di errore che non ti accorgi di aver fatto.
GIORNATA_INIZIALE = re.compile(
    r"(?:dalla|dall'|a partire dalla|si parte dalla|partiamo dalla|"
    r"iniziamo dalla|inizia dalla|comincia dalla|parte dalla)?\s*"
    r"(\d{1,2})\s*[aª°]?\s*giornata|giornata\s*(\d{1,2})",
    re.IGNORECASE,
)
PAROLE_CREDITI = {"crediti", "credit", "budget"}
NEGAZIONI = ("senza", "no ", "niente", "non ")
PAROLE_MODIFICATORE = ("modificatore", "modific", " mod", "md ", "difesa modificata")
PAROLE_BUSTE = (
    "buste",
    "busta",
    "offerte segrete",
    "offerta segreta",
    "asta silenziosa",
    "al buio",
    "offerte chiuse",
)


@dataclass(frozen=True)
class Regole:
    """Quello che si e' capito, e quello che non era scritto resta None."""

    crediti: int | None = None
    n_squadre: int | None = None
    slot: dict[str, int] | None = None
    modificatore_difesa: bool | None = None
    offerte_segrete: bool | None = None
    prima_giornata: int | None = None

    @property
    def vuote(self) -> bool:
        return all(
            v is None
            for v in (
                self.crediti,
                self.n_squadre,
                self.slot,
                self.modificatore_difesa,
                self.offerte_segrete,
                self.prima_giornata,
            )
        )


def leggi(testo: str) -> Regole:
    """Estrae le regole da una frase, senza pretendere un ordine."""
    testo = " " + (testo or "").strip().lower() + " "
    crediti: int | None = None
    squadre: int | None = None
    slot: dict[str, int] | None = None
    prima: int | None = None

    # 0. Da che giornata si comincia. Prima di tutto il resto, e tolta
    #    subito: quel numero e' piccolo come il numero di squadre.
    inizio = GIORNATA_INIZIALE.search(testo)
    if inizio:
        numero = int(inizio.group(1) or inizio.group(2))
        if 1 <= numero <= 38:
            prima = numero
            testo = testo[: inizio.start()] + " " + testo[inizio.end() :]

    # 1. La rosa: quattro numeri legati fra loro. Si toglie subito dal testo,
    #    altrimenti i suoi pezzi verrebbero riletti come crediti o squadre.
    trovata = ROSA.search(testo)
    if trovata:
        numeri = [int(n) for n in trovata.groups()]
        if all(1 <= n <= 30 for n in numeri):
            slot = dict(zip(RUOLI, numeri, strict=True))
            testo = testo[: trovata.start()] + " " + testo[trovata.end() :]

    # 2. I numeri che dicono cosa sono, perche' hanno la parola accanto.
    for pezzo in NUMERO_CON_PAROLA.finditer(testo):
        numero_prima, parola_dopo, parola_prima, numero_dopo = pezzo.groups()
        numero = int(numero_prima or numero_dopo)
        parola = (parola_dopo or parola_prima or "").lower()
        if parola in PAROLE_CREDITI:
            crediti = numero
        elif 2 <= numero <= 20:
            squadre = numero
    testo_pulito = NUMERO_CON_PAROLA.sub(" ", testo)

    # 3. I numeri rimasti soli: si riconoscono dalla taglia. Nessuna lega ha
    #    50 squadre e nessuna ha 8 crediti.
    for grezzo in re.findall(r"\b\d{1,5}\b", testo_pulito):
        numero = int(grezzo)
        if numero >= 50 and crediti is None:
            crediti = numero
        elif 2 <= numero <= 20 and squadre is None:
            squadre = numero

    return Regole(
        crediti=crediti,
        n_squadre=squadre,
        slot=slot,
        modificatore_difesa=_acceso(testo, PAROLE_MODIFICATORE),
        offerte_segrete=_acceso(testo, PAROLE_BUSTE),
        prima_giornata=prima,
    )


def _acceso(testo: str, parole: tuple[str, ...]) -> bool | None:
    """Acceso, spento, o non pervenuto - che non e' la stessa cosa di spento."""
    posizione = next((testo.find(p) for p in parole if p in testo), -1)
    if posizione < 0:
        return None
    # "senza modificatore" e "no mod" dicono il contrario della stessa parola:
    # si guarda cosa c'e' subito prima.
    prima = testo[max(0, posizione - 14) : posizione]
    return not any(n in prima for n in NEGAZIONI)


def descrivi(parametri, prudenza: float, prima_giornata: int = 1) -> str:
    """Le regole in chiaro, per rileggerle prima di cominciare."""
    slot = parametri.slot
    righe = [
        "<b>Le regole di questa lega</b>",
        f"<code>crediti      {parametri.crediti}</code>",
        f"<code>squadre      {parametri.n_squadre}</code>",
        f"<code>rosa         {slot['p']}-{slot['d']}-{slot['c']}-{slot['a']} "
        f"({parametri.slot_per_squadra} giocatori)</code>",
        f"<code>modificatore {'sì' if parametri.modificatore_difesa else 'no'}</code>",
        f"<code>asta         "
        f"{'a buste chiuse' if parametri.offerte_segrete else 'a rilancio'}</code>",
        f"<code>prudenza     {prudenza:.2f}</code>",
        f"<code>si comincia  {prima_giornata}ª giornata</code>",
        "",
        "<i>Per cambiarne una sola, riscrivi solo quella:</i>",
        "<code>/setup con modificatore</code>",
        "<code>/setup 10 squadre</code>",
        "<code>/setup dalla 4a giornata</code>",
    ]
    if parametri.offerte_segrete:
        righe.append(
            "\n<b>A buste chiuse</b> non ti dico la cifra che basterebbe a "
            "superare gli altri: non c'e' un secondo giro, quindi la cifra "
            "giusta e' il tuo massimo."
        )
    if parametri.modificatore_difesa:
        righe.append(
            "\n<b>Con il modificatore acceso</b> conta la media voto di "
            "portiere e difensori, non i loro bonus: il difensore che non "
            "prende gol vale piu' di quello che ogni tanto ne segna uno."
        )
    return "\n".join(righe)
