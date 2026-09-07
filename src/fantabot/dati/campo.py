"""Chi sta giocando davvero, adesso: minuti in campo e formazioni previste.

PERCHE' ESISTE. Il listone e lo storico dicono quanto un giocatore ha reso
quando ha giocato. Non dicono se giochera'. E' una differenza che a settembre
vale mezza asta: il 6 settembre 2026, con tre giornate alle spalle, il motore
consigliava Milinkovic-Savic come seconda occasione del listone a un credito,
e Milinkovic-Savic aveva **zero minuti** — Meret li aveva giocati tutti e
duecentosettanta. La stima era giusta sul giocatore e inutile sulla stagione.

Il listone non puo' saperlo per costruzione: e' una fotografia di agosto, e il
mercato, gli infortuni e le scelte dell'allenatore succedono dopo. Serve una
fonte che guardi il campo.

DUE FONTI, PERCHE' RISPONDONO A DUE DOMANDE DIVERSE:

  · **fotmob** dice chi ha giocato, e per quanti minuti. E' il passato
    misurato, e i minuti sono il denominatore giusto: chi entra al 75' per tre
    partite ha tre presenze e quarantacinque minuti, e chiamarlo titolare
    sarebbe un errore che le sole presenze non vedono.
  · **sportsgambler** dice chi giochera' la prossima. E' l'unico modo di
    sapere che un titolare fermo per infortunio sta per rientrare: nei minuti
    quel giocatore e' indistinguibile da una riserva.

Nessuna delle due ha un lucchetto: JSON e HTML serviti a chiunque, nessuna
chiave, nessun browser. Le ha trovate il progetto `pronostici`, che le usa da
GitHub Actions dal 24 agosto 2026; qui sono riscritte su httpx perche' i due
progetti non condividono l'ambiente, e una dipendenza fra due repository che
si aggiornano a ritmi diversi e' un guasto che aspetta il giorno sbagliato.

QUELLO CHE QUESTO MODULO NON FA. Non decide quanto pesano i minuti: lo fa
`motore/valutazione.py`, e con molta prudenza. Tre giornate sono un campione
piccolo, e un modulo che scarica dati non e' il posto dove si decide quanto
crederci.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

# L'identificativo di fotmob per la Serie A. Verificato il 6 settembre 2026
# leggendo il nome che torna nella risposta: dice "Serie A".
LEGA = 55
INDICE = "https://www.fotmob.com/api/data/leagues?id={}"
SPORTSGAMBLER = "https://www.sportsgambler.com"
PAGINA_FORMAZIONI = "/lineups/football/italy-serie-a/"
FRAMMENTO_FORMAZIONE = "/lineups/lineups-load2.php?id={}"

# Il default di httpx e' una sigla che fa scattare i filtri piu' grossolani
# senza che nessuno abbia deciso niente su di noi. Questo e' il valore che un
# sito si aspetta.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

# LA STAGIONE NON SI SCRIVE A MANO. Il suo identificativo cambia ogni anno e
# non e' deducibile: sta gia' composto dentro `fetchAllUrl` nella risposta
# dell'indice, e si rilegge da li' ogni volta. Cablarlo significherebbe che a
# luglio prossimo questo modulo legge i minuti dell'anno scorso senza che
# niente diventi rosso — il caso peggiore, perche' il numero resta plausibile.
MINUTI = "mins_played"
VOTO = "rating"

# Come fotmob scrive i venti club, e la sigla che usa il listone. Misurate il
# 6 settembre 2026 sulla lista completa: venti su venti, nessuna avanzata.
SQUADRE: dict[str, str] = {
    "Atalanta": "ATA",
    "Bologna": "BOL",
    "Cagliari": "CAG",
    "Como": "COM",
    "Fiorentina": "FIO",
    "Frosinone": "FRO",
    "Genoa": "GEN",
    "Internazionale": "INT",
    "Juventus": "JUV",
    "Lazio": "LAZ",
    "Lecce": "LEC",
    "Milan": "MIL",
    "Monza": "MON",
    "Napoli": "NAP",
    "Parma": "PAR",
    "Roma": "ROM",
    "Sassuolo": "SAS",
    "Torino": "TOR",
    "Udinese": "UDI",
    "Venezia": "VEN",
}

# Lettere che la scomposizione Unicode non separa, perche' non sono una
# lettera piu' un accento: sono lettere loro. Senza queste, "Hojlund" del
# listone non raggiunge "Hojlund" scritto con la o barrata, e "Ostigard" non
# raggiunge la sua.
LETTERE = str.maketrans(
    {"ø": "o", "đ": "d", "ð": "d", "ł": "l", "æ": "ae",
     "œ": "oe", "ß": "ss", "þ": "th"}
)
# Le quattro forme di apostrofo che i due siti usano per lo stesso nome. Senza
# questa riga "N'Dri" del listone e "N'Dri" di fotmob sono due persone.
APOSTROFI = str.maketrans(
    {"’": "'", "‘": "'", "`": "'", "´": "'"}
)

# Sotto queste lettere un prefisso non identifica nessuno: "val" sta in
# "Valdepenas" e in "Valentini".
PREFISSO_MINIMO = 4
MINUTI_PARTITA = 90.0
# Sopra questa quota di minuti si e' titolari. Non e' una soglia del motore —
# che i minuti li usa come numero continuo — ma di come si scrive la scheda:
# sotto, "titolare" sarebbe una parola piu' grossa del dato.
QUOTA_DA_TITOLARE = 0.60


class FonteNonRaggiungibile(RuntimeError):
    """La fonte non ha risposto. Si resta con quello che c'era prima."""


@dataclass
class Rendimento:
    """Cosa ha fatto in campo un giocatore, finora, in questa stagione."""

    nome: str
    squadra: str
    minuti: int = 0
    presenze: int = 0
    voto_fotmob: float | None = None
    # Quante giornate ha giocato la SUA squadra. E' il denominatore giusto:
    # chi ha una partita in meno perche' la sua era rinviata non deve
    # risultare riserva.
    giornate_squadra: int = 0
    previsto_titolare: bool | None = None

    @property
    def quota_minuti(self) -> float:
        """La frazione di minuti disponibili che ha giocato. 1 = sempre tutti."""
        disponibili = MINUTI_PARTITA * self.giornate_squadra
        if disponibili <= 0:
            return 0.0
        return min(1.0, self.minuti / disponibili)

    @property
    def titolare(self) -> bool:
        """Vero quando i minuti dicono titolare, non quando li ha sfiorati."""
        return self.quota_minuti >= QUOTA_DA_TITOLARE


@dataclass
class Formazioni:
    """Gli undici previsti per le prossime partite, squadra per squadra.

    Legati alla squadra e non buttati in un insieme unico, perche' senza la
    squadra non si distingue "non e' previsto titolare" da "la sua partita non
    l'abbiamo ancora letta" — e sono due cose opposte da dire a chi offre.
    """

    per_squadra: dict[str, set[str]] = field(default_factory=dict)

    @property
    def squadre_lette(self) -> set[str]:
        return {s for s, n in self.per_squadra.items() if n}


# --------------------------------------------------------------- i nomi


def parti(nome: str) -> tuple[list[str], str]:
    """Le parole di un nome, e le iniziali puntate che stavano in fondo.

    Il listone scrive il cognome e disambigua con le iniziali — "Marin R.",
    "Esposito F.P.", "Ederson D.S." — mentre fotmob scrive il nome intero. Le
    iniziali non vanno confrontate come parole (nessun nome intero contiene la
    parola "r"), ma non vanno nemmeno buttate: sono esattamente cio' che
    distingue due omonimi della stessa squadra.
    """
    testo = nome.translate(APOSTROFI).lower().translate(LETTERE)
    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    # Le iniziali si riconoscono PRIMA di togliere la punteggiatura: dopo,
    # "d.s." e "ds" sono indistinguibili da un cognome corto.
    coda = re.search(r"((?:\b[a-z]\.\s*)+)$", testo)
    iniziali = "".join(re.findall(r"[a-z]", coda.group(1))) if coda else ""
    if coda:
        testo = testo[: coda.start()]
    parole = [p for p in re.split(r"[^a-z]+", testo.replace("'", "")) if p]
    return parole, iniziali


def chiave(nome: str) -> str:
    """Il nome ridotto alla forma con cui due fonti diverse si incontrano."""
    return " ".join(parti(nome)[0])


def _compatibile(nostre: list[str], iniziali: str, loro: list[str]) -> bool:
    """Le iniziali del listone trovano posto fra le parole che restano?"""
    if not iniziali:
        return True
    resto = [p for p in loro if p not in nostre]
    if not resto:
        # Anche loro scrivono solo il cognome: le iniziali non contraddicono
        # niente, e pretendere una conferma che non puo' arrivare perderebbe
        # l'aggancio.
        return True
    return any(p.startswith(i) for i in iniziali for p in resto)


def abbina(
    nostri: list[tuple[int, str, str]], loro: dict[str, list[Rendimento]]
) -> dict[int, Rendimento]:
    """Aggancia il listone ai giocatori di fotmob, squadra per squadra.

    LA SQUADRA VIENE PRIMA DEL NOME, ed e' quello che rende sicuro il resto:
    dentro una rosa i candidati sono venti, e due cognomi uguali nella stessa
    squadra sono abbastanza rari da poterli rifiutare invece che indovinarli.

    Tre passate, e l'ordine conta.

      1. **Esatta**: ogni nostra parola si ritrova fra le loro.
      2. **Sull'ultima parola sola**, che e' il cognome vero: il nostro "Zambo
         Anguissa" contro il loro "Frank Anguissa" non condivide "zambo", e
         pretendere tutte le parole perderebbe un titolare del Napoli.
      3. **Per prefisso**, solo su chi e' avanzato da entrambe le parti:
         fotmob accorcia certi nomi come li accorcia lo stadio ("Valde" per
         Valdepenas). Cercare i prefissi prima lascerebbe che un soprannome
         porti via un giocatore a cui sarebbe toccata la riga giusta.

    UN AGGANCIO AMBIGUO SI SCARTA. Attribuire i minuti di uno al compagno
    produce un numero plausibile sulla persona sbagliata: un errore che nessun
    controllo vede, perche' il risultato non e' assurdo — e' solo falso.
    """
    esito: dict[int, Rendimento] = {}
    for sigla in {s for _, _, s in nostri}:
        candidati = loro.get(sigla, [])
        if not candidati:
            continue
        # Le loro parole si calcolano una volta sola: `abbina` gira su
        # seicento giocatori per venti squadre.
        loro_parti = {id(r): parti(r.nome)[0] for r in candidati}
        liberi = {id(r) for r in candidati}
        aperti: list[tuple[int, list[str], str]] = []

        for id_fc, nome, s in nostri:
            if s != sigla:
                continue
            nostre, iniziali = parti(nome)
            if not nostre:
                continue
            trovati = [
                r
                for r in candidati
                if id(r) in liberi
                and all(p in loro_parti[id(r)] for p in nostre)
                and _compatibile(nostre, iniziali, loro_parti[id(r)])
            ]
            if not trovati and len(nostre) > 1:
                trovati = [
                    r
                    for r in candidati
                    if id(r) in liberi and nostre[-1] in loro_parti[id(r)]
                ]
            if len(trovati) == 1:
                esito[id_fc] = trovati[0]
                liberi.discard(id(trovati[0]))
            elif not trovati:
                aperti.append((id_fc, nostre, iniziali))
            else:
                log.info("aggancio ambiguo per %s (%s): scartato", nome, sigla)

        for id_fc, nostre, _ in aperti:
            trovati = [
                r
                for r in candidati
                if id(r) in liberi
                and any(
                    len(sua) >= PREFISSO_MINIMO and nostra.startswith(sua)
                    for nostra in nostre
                    for sua in loro_parti[id(r)]
                )
            ]
            if len(trovati) == 1:
                esito[id_fc] = trovati[0]
                liberi.discard(id(trovati[0]))
    return esito


# --------------------------------------------------------------- fotmob


def _json(client: httpx.Client, url: str) -> dict:
    try:
        risposta = client.get(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        risposta.raise_for_status()
        grezzo = risposta.content
    except httpx.HTTPError as e:
        raise FonteNonRaggiungibile(f"{url}: {e}") from e
    # Il CDN manda gzip anche a chi non lo ha negoziato, e allora il client
    # non lo scompatta: senza questa riga l'errore parla di JSON malformato e
    # manda a cercare il problema nel posto sbagliato.
    if grezzo[:2] == b"\x1f\x8b":
        grezzo = gzip.decompress(grezzo)
    try:
        return json.loads(grezzo.decode("utf-8"))
    except ValueError as e:
        raise FonteNonRaggiungibile(f"{url}: risposta non JSON ({e})") from e


def indirizzi(client: httpx.Client, *, indice: dict | None = None) -> dict[str, str]:
    """Dove stanno, oggi, i minuti e i voti della stagione in corso."""
    if indice is None:
        indice = _json(client, INDICE.format(LEGA))
    elenco = ((indice.get("stats") or {}).get("players")) or []
    return {
        v["name"]: v["fetchAllUrl"]
        for v in elenco
        if v.get("name") in (MINUTI, VOTO) and v.get("fetchAllUrl")
    }


def _righe(dati: dict) -> list[dict]:
    return [
        r for lista in (dati.get("TopLists") or []) for r in (lista.get("StatList") or [])
    ]


def leggi_minuti(
    client: httpx.Client | None = None, *, frammenti: dict[str, dict] | None = None
) -> dict[str, list[Rendimento]]:
    """Minuti, presenze e voto di ogni giocatore, raggruppati per sigla.

    `frammenti` esiste per i test: sono le stesse risposte, gia' in mano.
    """
    proprio = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        if frammenti is None:
            dove = indirizzi(client)
            if MINUTI not in dove:
                # A stagione non ancora cominciata `stats.players` e' vuoto.
                # E' un "non ancora", non un guasto.
                return {}
            frammenti = {n: _json(client, u) for n, u in dove.items()}
    finally:
        if proprio:
            client.close()

    per_sigla: dict[str, list[Rendimento]] = {}
    indice: dict[tuple[str, str], Rendimento] = {}
    for riga in _righe(frammenti.get(MINUTI) or {}):
        sigla = SQUADRE.get(riga.get("TeamName") or "")
        nome = (riga.get("ParticipantName") or "").strip()
        if not sigla or not nome:
            continue
        r = Rendimento(
            nome=nome,
            squadra=sigla,
            minuti=int(riga.get("MinutesPlayed") or 0),
            presenze=int(riga.get("MatchesPlayed") or 0),
        )
        per_sigla.setdefault(sigla, []).append(r)
        indice[(sigla, nome)] = r

    for riga in _righe(frammenti.get(VOTO) or {}):
        sigla = SQUADRE.get(riga.get("TeamName") or "")
        r = indice.get((sigla or "", (riga.get("ParticipantName") or "").strip()))
        if r is not None and riga.get("StatValue") is not None:
            r.voto_fotmob = round(float(riga["StatValue"]), 2)

    # LE GIORNATE SI CONTANO DALLA ROSA, non da un calendario. Una squadra ha
    # giocato almeno quante partite ne ha giocate il suo giocatore piu'
    # presente, e chiedere il calendario a una terza fonte per un numero che
    # e' gia' qui vorrebbe dire aggiungere una cosa che si puo' rompere.
    for elenco in per_sigla.values():
        giornate = max((r.presenze for r in elenco), default=0)
        for r in elenco:
            r.giornate_squadra = giornate
    return per_sigla


# --------------------------------------------------------------- sportsgambler


def _testo(client: httpx.Client, percorso: str, referer: str = "") -> str:
    testate = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        # Il frammento e' pensato per essere chiesto dalla sua pagina: queste
        # due testate sono quelle che manderebbe il browser, e ometterle vuol
        # dire chiedere a un sito di comportarsi come non ha mai previsto.
        testate["Referer"] = referer
        testate["X-Requested-With"] = "XMLHttpRequest"
    try:
        risposta = client.get(f"{SPORTSGAMBLER}{percorso}", headers=testate)
        risposta.raise_for_status()
        return risposta.text
    except httpx.HTTPError as e:
        raise FonteNonRaggiungibile(f"{percorso}: {e}") from e


# L'identificativo della partita NON sta in un link: la riga del cartellone e'
# un elemento cliccabile, e il numero vive dentro il suo `onClick`. Cercare un
# `href` verso il frammento dava zero risultati e una pagina che risponde 200 —
# il modo piu' silenzioso di non avere formazioni.
CARTELLONE = re.compile(
    r'class="fxs-team home"[^>]*>(?P<casa>[^<]*)<'
    r'|class="fxs-team"[^>]*>(?P<ospiti>[^<]*)<'
    r'|onClick="reply_click\((?P<id>\d+)\)"'
)
GIOCATORE = re.compile(
    r'class="player-profile"[^>]*>[^<]*<.*?class="player-name"[^>]*>([^<]*)<', re.S
)

# Come sportsgambler scrive i venti club. Diciotto coincidono con fotmob e si
# riconoscono da soli; questi due no, e sono proprio quelli che il
# riconoscimento generico sbaglierebbe: "Inter Milan" contiene "Milan", e senza
# una riga esplicita gli undici dell'Inter finirebbero al Milan.
ALIAS_SQUADRE: dict[str, str] = {
    "ac milan": "MIL",
    "inter milan": "INT",
}


def _sigla(nome: str) -> str | None:
    """La sigla del listone per come sportsgambler scrive un club."""
    pulito = " ".join(parti(nome)[0])
    if pulito in ALIAS_SQUADRE:
        return ALIAS_SQUADRE[pulito]
    for loro, sigla in SQUADRE.items():
        if " ".join(parti(loro)[0]) == pulito:
            return sigla
    return None


def _cartellone(html: str) -> list[tuple[str, str | None, str | None]]:
    """Le partite in elenco: identificativo e le due squadre, in ordine.

    Una sola scansione in ordine di documento, perche' le tre cose sono
    fratelli nel markup e cercarle separatamente perderebbe proprio il legame
    fra loro.
    """
    partite: list[tuple[str, str | None, str | None]] = []
    casa = ospiti = None
    for m in CARTELLONE.finditer(html):
        if m.group("casa") is not None:
            casa = m.group("casa").strip()
        elif m.group("ospiti") is not None:
            ospiti = m.group("ospiti").strip()
        elif m.group("id"):
            partite.append((m.group("id"), casa, ospiti))
            casa = ospiti = None
    return partite


def _lati(frammento: str) -> tuple[list[str], list[str]]:
    """I nomi di casa e quelli ospiti, separati dove comincia il secondo.

    IL TAGLIO E' L'UNICA LETTURA CHE REGGE. La fine del blocco di casa non e'
    marcata da niente: e' semplicemente dove comincia quello ospite, e i tag
    annidati non si contano con un'espressione regolare.
    """
    inizio_casa = frammento.find('class="lineups-home')
    inizio_ospiti = frammento.find('class="lineups-away')
    if inizio_casa == -1 or inizio_ospiti <= inizio_casa:
        return [], []

    def nomi(pezzo: str) -> list[str]:
        return [n for n in (chiave(x) for x in GIOCATORE.findall(pezzo)) if n]

    return (
        nomi(frammento[inizio_casa:inizio_ospiti]),
        nomi(frammento[inizio_ospiti:]),
    )


def leggi_formazioni(
    client: httpx.Client | None = None,
    *,
    limite: int = 10,
    elenco_html: str | None = None,
    frammenti: list[tuple[str, str | None, str | None, str]] | None = None,
) -> Formazioni:
    """Gli undici previsti per le prossime partite di Serie A.

    Due passi, e il secondo non e' facoltativo: la pagina di elenco NON
    contiene i giocatori, li carica dopo in AJAX. Chi si fermasse al primo
    troverebbe 200 e zero formazioni.

    Il `limite` sono le partite piu' vicine nel tempo, che stanno in cima:
    dieci bastano per una giornata intera di Serie A, e chiedere le
    quaranta in cartellone vorrebbe dire quaranta richieste per sapere tre
    volte la stessa cosa.

    Se la fonte non risponde si torna a mani vuote invece di sollevare: le
    formazioni previste sono un di piu', e un'asta non si ferma perche' un
    sito e' giu'.
    """
    proprio = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    esito = Formazioni()
    try:
        if frammenti is None:
            if elenco_html is None:
                elenco_html = _testo(client, PAGINA_FORMAZIONI)
            frammenti = [
                (
                    ident,
                    casa,
                    ospiti,
                    _testo(
                        client,
                        FRAMMENTO_FORMAZIONE.format(ident),
                        referer=f"{SPORTSGAMBLER}{PAGINA_FORMAZIONI}",
                    ),
                )
                for ident, casa, ospiti in _cartellone(elenco_html)[:limite]
            ]
    except FonteNonRaggiungibile as e:
        log.warning("formazioni previste non lette: %s", e)
        return esito
    finally:
        if proprio:
            client.close()

    for _, casa, ospiti, frammento in frammenti:
        nomi_casa, nomi_ospiti = _lati(frammento)
        for squadra, nomi in ((casa, nomi_casa), (ospiti, nomi_ospiti)):
            sigla = _sigla(squadra or "")
            # Un lato vuoto non e' "nessun titolare": e' una partita di cui il
            # sito non ha ancora pubblicato la formazione. Registrarlo
            # direbbe che undici titolari sono in panchina.
            if sigla and nomi:
                esito.per_squadra.setdefault(sigla, set()).update(nomi)
    return esito


# --------------------------------------------------------------- persistenza


def salva(conn: sqlite3.Connection, rendimenti: dict[int, Rendimento]) -> None:
    """Sostituisce la fotografia precedente. Non si accumula: si rilegge."""
    conn.execute("DELETE FROM campo")
    conn.executemany(
        """
        INSERT INTO campo (
            id_fc, minuti, presenze, giornate_squadra, voto_fotmob, previsto_titolare
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                id_fc,
                r.minuti,
                r.presenze,
                r.giornate_squadra,
                r.voto_fotmob,
                None if r.previsto_titolare is None else int(r.previsto_titolare),
            )
            for id_fc, r in rendimenti.items()
        ],
    )
    conn.commit()


def leggi(conn: sqlite3.Connection) -> dict[int, Rendimento]:
    """Quello che si sa del campo, per id del listone."""
    esito: dict[int, Rendimento] = {}
    for r in conn.execute(
        "SELECT c.*, g.nome, g.squadra FROM campo c JOIN giocatori g ON g.id_fc = c.id_fc"
    ):
        esito[r["id_fc"]] = Rendimento(
            nome=r["nome"],
            squadra=r["squadra"],
            minuti=r["minuti"],
            presenze=r["presenze"],
            giornate_squadra=r["giornate_squadra"],
            voto_fotmob=r["voto_fotmob"],
            previsto_titolare=(
                None if r["previsto_titolare"] is None else bool(r["previsto_titolare"])
            ),
        )
    return esito


def _giornate_per_squadra(per_sigla: dict[str, list[Rendimento]]) -> dict[str, int]:
    return {
        sigla: max((r.giornate_squadra for r in elenco), default=0)
        for sigla, elenco in per_sigla.items()
    }


def innesta_previsioni(
    nostri: list[tuple[int, str, str]],
    rendimenti: dict[int, Rendimento],
    previsti: Formazioni,
    giornate: dict[str, int],
) -> None:
    """Segna chi e' previsto titolare, e aggiunge chi finora non era mai sceso.

    QUEST'ULTIMA PARTE E' IL PUNTO. Chi non ha giocato un minuto non compare
    in fotmob, quindi non ha nessuna riga da segnare — ed e' esattamente il
    caso che interessa a un'asta: un titolare fermo per infortunio che sta per
    rientrare e' indistinguibile da una riserva finche' non lo si vede
    nell'undici previsto. Senza queste righe, il segnale che vale di piu'
    sarebbe l'unico che non arriva.

    Chi gioca in una squadra di cui NON abbiamo letto la formazione resta a
    `None`: non e' "non previsto", e' "non lo sappiamo".
    """
    if not previsti.squadre_lette:
        return
    # Gli undici previsti si agganciano al listone con la stessa macchina dei
    # minuti: stesso problema di nomi, stessa squadra a restringere il campo,
    # stesso rifiuto degli ambigui.
    finti = {
        sigla: [Rendimento(nome=n, squadra=sigla) for n in sorted(nomi)]
        for sigla, nomi in previsti.per_squadra.items()
        if nomi
    }
    in_campo = abbina(nostri, finti)

    for id_fc, _, sigla in nostri:
        if sigla not in previsti.squadre_lette:
            continue
        titolare = id_fc in in_campo
        r = rendimenti.get(id_fc)
        if r is None:
            # Anche chi non ha giocato un minuto E non e' previsto prende la
            # sua riga, con tutto a zero. Serve a distinguere "abbiamo
            # guardato e non c'e'" da "non abbiamo guardato": senza, un
            # portiere di riserva e un giocatore di cui non sappiamo niente
            # arrivano identici al motore.
            nome = in_campo[id_fc].nome if titolare else ""
            r = rendimenti[id_fc] = Rendimento(
                nome=nome, squadra=sigla, giornate_squadra=giornate.get(sigla, 0)
            )
        r.previsto_titolare = titolare


def aggiorna(
    conn: sqlite3.Connection, client: httpx.Client | None = None
) -> dict[str, int]:
    """Rilegge le due fonti e riscrive la tabella. Torna cosa e' entrato."""
    per_sigla = leggi_minuti(client)
    nostri = [
        (r["id_fc"], r["nome"], r["squadra"])
        for r in conn.execute("SELECT id_fc, nome, squadra FROM giocatori")
    ]
    rendimenti = abbina(nostri, per_sigla)
    previsti = leggi_formazioni(client)
    innesta_previsioni(nostri, rendimenti, previsti, _giornate_per_squadra(per_sigla))

    salva(conn, rendimenti)
    return {
        "letti": sum(len(v) for v in per_sigla.values()),
        "agganciati": len(rendimenti),
        "squadre_previste": len(previsti.squadre_lette),
        "previsti": sum(1 for r in rendimenti.values() if r.previsto_titolare),
        "giornate": max(
            (r.giornate_squadra for v in per_sigla.values() for r in v), default=0
        ),
    }
