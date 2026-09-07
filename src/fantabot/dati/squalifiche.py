"""Chi salta la prossima per squalifica, e chi rischia di saltare quella dopo.

DUE COSE DIVERSE, e vanno tenute separate perche' portano a due decisioni
opposte:

  · **squalificato** — domenica non gioca. E' un fatto, gia' deciso dal
    giudice sportivo, e vale zero punti qualunque cosa dica la fantamedia;
  · **diffidato** — domenica gioca, ma un altro giallo e salta quella dopo.
    Non toglie niente adesso: e' l'unica informazione che riguarda una
    formazione che non hai ancora fatto, ed e' il motivo per cui si mostra
    invece di essere trasformata in un numero.

PERCHE' NON BASTAVANO GLI INFORTUNI. Il bot vedeva che un giocatore non
scendeva in campo e non sapeva perche'; con gli infortunati ha imparato a
distinguere «e' fermo» da «e' una riserva». Una squalifica assomiglia a un
infortunio da una giornata, ma non la si legge da nessuna parte in quella
pagina — e schierare un squalificato costa un 6 politico in meno per una cosa
che era scritta.

NOTA ONESTA SULLA FONTE. La pagina e' renderizzata dal server e ha la stessa
forma di quella degli infortunati — schede per squadra, due colonne dentro —
ma nel momento in cui questo modulo e' stato scritto era **vuota per tutte e
venti le squadre**, come e' giusto dopo tre giornate: quattro cartellini in
tre partite non li prende nessuno. La struttura e' quella vera e i test la
riproducono, ma la prima lettura con dentro qualcuno sara' anche la prima
prova sul campo. Per questo `leggi` dichiara sempre quante schede ha visto:
zero squalificati su venti schede e' un'informazione, zero schede e' un
guasto, e le due cose non devono somigliarsi.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from .aggiorna import normalizza
from .infortuni import SQUADRE

log = logging.getLogger(__name__)

PAGINA = "https://www.fantacalcio.it/squalificati-e-diffidati-campionato-serie-a"

# Le due colonne dentro ogni scheda, riconosciute dall'etichetta. Non dalla
# posizione: una colonna in piu' domani sposterebbe tutto di uno, e un elenco
# di diffidati letto come squalificati farebbe saltare mezza formazione.
ETICHETTE = {"squalificat": "squalificato", "diffidat": "diffidato"}

# "2 giornate", "squalificato per 2 turni". Senza numero e' una sola.
GIORNATE = re.compile(r"(\d+)\s*(?:giornat|turn)", re.I)


@dataclass(frozen=True)
class Fermato:
    id_fc: int
    nome: str
    squadra: str
    giornate: int = 1
    diffidato: bool = False
    testo: str = ""


@dataclass
class Esito:
    schede: int = 0
    squalificati: list[Fermato] = field(default_factory=list)
    diffidati: list[Fermato] = field(default_factory=list)
    non_trovati: list[str] = field(default_factory=list)
    errore: str = ""

    @property
    def riuscito(self) -> bool:
        # Venti schede e nessun nome dentro e' un esito valido: vuol dire che
        # questa settimana non e' squalificato nessuno.
        return not self.errore and self.schede > 0


def _giornate_da(testo: str) -> int:
    trovato = GIORNATE.search(testo or "")
    return max(1, int(trovato.group(1))) if trovato else 1


def _nomi_nella_colonna(colonna) -> list[tuple[str, str]]:
    """I nomi di una colonna, con la frase che li accompagna.

    Si accettano due forme perche' il sito ne usa due nelle pagine gemelle:
    la voce strutturata con `.item-name`, e la riga semplice. Quando non c'e'
    ne' l'una ne' l'altra il testo della voce e' il nome, che e' il caso piu'
    povero e anche il piu' probabile.
    """
    trovati: list[tuple[str, str]] = []
    for voce in colonna.select("li"):
        elemento = voce.select_one(".item-name")
        nome = (elemento or voce).get_text(" ", strip=True)
        descrizione = voce.select_one(".item-description")
        testo = descrizione.get_text(" ", strip=True) if descrizione else ""
        if not testo and elemento is not None:
            # Il resto della riga, tolto il nome: spesso e' li' che sta il
            # numero di giornate.
            intero = voce.get_text(" ", strip=True)
            testo = intero.replace(nome, "", 1).strip()
        if nome:
            trovati.append((nome, testo))
    return trovati


def leggi(conn: sqlite3.Connection, html: str) -> Esito:
    """Le squalifiche di questa settimana, agganciate al listone per nome."""
    esito = Esito()
    zuppa = BeautifulSoup(html, "lxml")
    schede = zuppa.select(".team-card")
    if not schede:
        esito.errore = "la pagina non ha le schede per squadra: e' cambiata"
        return esito

    listone: dict[tuple[str, str], int] = {}
    per_nome: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id_fc, nome_cerca, squadra FROM giocatori"):
        listone[(r["nome_cerca"], r["squadra"])] = r["id_fc"]
        per_nome.setdefault(r["nome_cerca"], []).append(r["id_fc"])

    for scheda in schede:
        etichetta = scheda.select_one(".team-name")
        if etichetta is None:
            continue
        sigla = SQUADRE.get(etichetta.get_text(strip=True).lower())
        if sigla is None:
            continue
        esito.schede += 1
        for colonna in scheda.select(".col"):
            intestazione = colonna.select_one("header")
            titolo = intestazione.get_text(" ", strip=True).lower() if intestazione else ""
            genere = next(
                (v for k, v in ETICHETTE.items() if k in titolo), None
            )
            if genere is None:
                continue
            for nome, testo in _nomi_nella_colonna(colonna):
                chiave = normalizza(nome)
                # Prima il nome NELLA SUA SQUADRA: due omonimi in Serie A sono
                # normali, e uno squalificato assegnato all'altro e' una
                # formazione sbagliata due volte.
                id_fc = listone.get((chiave, sigla))
                if id_fc is None:
                    candidati = per_nome.get(chiave, [])
                    id_fc = candidati[0] if len(candidati) == 1 else None
                if id_fc is None:
                    esito.non_trovati.append(f"{nome} ({sigla})")
                    continue
                fermato = Fermato(
                    id_fc=id_fc,
                    nome=nome,
                    squadra=sigla,
                    giornate=_giornate_da(testo) if genere == "squalificato" else 0,
                    diffidato=genere == "diffidato",
                    testo=testo,
                )
                if fermato.diffidato:
                    esito.diffidati.append(fermato)
                else:
                    esito.squalificati.append(fermato)
    return esito


def salva(conn: sqlite3.Connection, esito: Esito) -> None:
    """Riscrive la tabella intera.

    Come per gli infortuni: non e' uno storico, e' lo stato di questa
    settimana. Un squalificato che ha scontato non va tenuto — sommare due
    letture vorrebbe dire tenerlo fuori per il doppio del dovuto.
    """
    conn.execute("DELETE FROM squalifiche")
    conn.executemany(
        "INSERT OR REPLACE INTO squalifiche (id_fc, giornate, diffidato, testo)"
        " VALUES (?, ?, ?, ?)",
        [
            (f.id_fc, f.giornate, int(f.diffidato), f.testo)
            for f in esito.squalificati + esito.diffidati
        ],
    )
    conn.commit()


def aggiorna(conn: sqlite3.Connection, client: httpx.Client | None = None) -> Esito:
    proprio = client is None
    client = client or httpx.Client(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        risposta = client.get(PAGINA)
        risposta.raise_for_status()
        esito = leggi(conn, risposta.text)
    except httpx.HTTPError as e:
        return Esito(errore=f"non riesco a leggere le squalifiche: {e}")
    finally:
        if proprio:
            client.close()
    if esito.riuscito:
        salva(conn, esito)
    return esito


def carica(conn: sqlite3.Connection) -> dict[int, tuple[int, bool, str]]:
    """Per ogni id: giornate di squalifica, se e' diffidato, e la frase."""
    return {
        r["id_fc"]: (r["giornate"], bool(r["diffidato"]), r["testo"])
        for r in conn.execute(
            "SELECT id_fc, giornate, diffidato, testo FROM squalifiche"
        )
    }
