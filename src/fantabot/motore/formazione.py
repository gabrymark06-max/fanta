"""Chi schierare domenica, e con che modulo.

DUE NUMERI PER OGNI GIOCATORE, e vanno tenuti separati come prezzo e valore:

  · **quanto rende quando gioca** — la fantamedia attesa, corretta da come sta
    andando nelle ultime giornate;
  · **quanto e' probabile che giochi** — che a settembre e' l'informazione
    scarsa, e che nessuna fantamedia contiene.

Il prodotto dei due e' quello che si mette in campo. E' la stessa distinzione
dell'asta, spostata di una settimana: un attaccante da 8 di fantamedia che
gioca mezz'ora rende meno di uno da 6,5 che gioca sempre, e la classifica per
fantamedia dice il contrario.

IL MODULO NON SI SCEGLIE PRIMA. Si provano tutti quelli ammessi e vince quello
che somma di piu': scegliere "il mio 3-5-2" e poi riempirlo e' il modo piu'
comune di lasciare in panchina il miglior giocatore che si ha.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .asta import Squadra, StatoAsta
from .valutazione import PESO_MODIFICATORE, RUOLI_DELLA_DIFESA, Valutazione

# I moduli di Classic, come (difensori, centrocampisti, attaccanti).
MODULI: tuple[tuple[int, int, int], ...] = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
)

# Quanto pesa la forma recente contro la fantamedia di stagione. Un terzo: tre
# giornate sono poche per riscrivere un giocatore e troppe per ignorarle, e
# chi le ignora schiera per fama invece che per stato di forma.
PESO_FORMA = 1 / 3

# La media voto attorno a cui gira il modificatore di difesa: sotto si perde,
# sopra si guadagna.
VOTO_NEUTRO = 6.0

# Quanti elementi della difesa entrano nel modificatore: il portiere piu' i
# tre difensori con il voto piu' alto, che e' la regola piu' diffusa.
DIFENSORI_NEL_MODIFICATORE = 3


# Quanto l'avversario sposta la fantamedia attesa, in punti, fra la partita
# piu' facile e la piu' difficile del campionato. Tre decimi per lato: e' meno
# di quanto crede chi guarda il calendario e piu' di quanto crede chi guarda
# solo la fantamedia. Un titolare forte contro la prima in classifica resta
# meglio di una riserva contro l'ultima — e' esattamente questo il confine che
# il numero deve tenere.
MASSIMO_EFFETTO_AVVERSARIO = 0.30


@dataclass(frozen=True)
class Avversario:
    """Chi si incontra domenica, e quanto pesa."""

    sigla: str
    in_casa: bool
    difficolta: float  # da -1 (la partita piu' facile) a +1

    @property
    def dove(self) -> str:
        return "in casa" if self.in_casa else "fuori"


@dataclass(frozen=True)
class Schierato:
    """Un giocatore valutato per domenica, non per la stagione."""

    valutazione: Valutazione
    gioca: float  # da 0 a 1
    rende: float  # fantamedia attesa, corretta dalla forma e dall'avversario
    nota: str = ""
    avversario: Avversario | None = None

    @property
    def punti(self) -> float:
        return self.gioca * self.rende

    @property
    def nome(self) -> str:
        return self.valutazione.giocatore.nome

    @property
    def ruolo(self) -> str:
        return self.valutazione.giocatore.ruolo


@dataclass(frozen=True)
class Consiglio:
    modulo: tuple[int, int, int]
    titolari: list[Schierato]
    panchina: list[Schierato]
    punti: float
    avvisi: list[str] = field(default_factory=list)

    @property
    def nome_modulo(self) -> str:
        return "-".join(str(n) for n in self.modulo)


def probabilita_che_giochi(v: Valutazione) -> tuple[float, str]:
    """Quanto e' probabile che scenda in campo, e perche'.

    L'ordine delle risposte e' l'ordine di quanto sono affidabili: un
    infortunio dichiarato batte una formazione prevista, che batte i minuti
    delle giornate passate. Ognuna sa qualcosa che le altre non sanno, e la
    prima che parla ha ragione.
    """
    g = v.giocatore
    # PRIMA DI TUTTO IL RESTO. Una squalifica non e' una previsione: e' gia'
    # scritta nel comunicato del giudice sportivo, e nessun dato sui minuti
    # puo' smentirla. Sta sopra anche all'infortunio perche' non ha gradi —
    # o la sconta o non la sconta.
    if g.squalificato >= 1:
        quante = g.squalificato
        return 0.0, f"squalificato, {quante} giornat{'a' if quante == 1 else 'e'}"
    if g.fermo is not None and g.fermo.giornate_fuori >= 1:
        quante = g.fermo.giornate_fuori
        return 0.0, f"fermo, {quante} giornat{'a' if quante == 1 else 'e'}"
    if g.fermo is not None:
        # Zero giornate ma una scheda: e' un "in dubbio", e vale meta'.
        return 0.5, "in dubbio"
    if g.campo is None or g.campo.giornate <= 0:
        return 0.5, "non so se gioca"
    if g.campo.previsto_titolare is True:
        return 1.0, "previsto titolare"
    quota = g.campo.quota_minuti
    if g.campo.previsto_titolare is False and quota < 0.6:
        return min(quota, 0.35), "fuori dagli undici previsti"
    return quota, f"{round(quota * 100)}% dei minuti"


def rendimento_atteso(
    v: Valutazione, forma: float | None, avversario: Avversario | None = None
) -> float:
    """La fantamedia di stagione, tirata verso le ultime giornate e la prossima.

    Tre informazioni diverse su tre orizzonti diversi: quanto vale in stagione,
    come sta adesso, e chi ha davanti domenica. Le prime due si mescolano, la
    terza si somma — perche' non e' una revisione del giocatore, e' il campo su
    cui gioca questa volta.
    """
    base = (
        v.fantamedia_attesa
        if forma is None
        else (1 - PESO_FORMA) * v.fantamedia_attesa + PESO_FORMA * forma
    )
    if avversario is None:
        return base
    peso = min(max(avversario.difficolta, -1.0), 1.0)
    return base - MASSIMO_EFFETTO_AVVERSARIO * peso


def valuta_per_domenica(
    stato: StatoAsta,
    squadra: Squadra,
    forma: dict[int, float] | None = None,
    avversari: dict[str, Avversario] | None = None,
) -> list[Schierato]:
    """Tutta la rosa, ordinata per quanto rende domenica.

    Senza `avversari` funziona come prima: il calendario e' un di piu', non un
    requisito, e un bot che smette di consigliare la formazione perche' non sa
    chi si gioca la giornata dopo sarebbe peggio di uno che non l'ha mai
    saputo.
    """
    forma = forma or {}
    avversari = avversari or {}
    schierabili: list[Schierato] = []
    for acquisto in squadra.acquisti:
        v = stato.valutazioni.get(acquisto.id_fc)
        if v is None:
            continue
        gioca, nota = probabilita_che_giochi(v)
        contro = avversari.get(v.giocatore.squadra)
        if contro is None and avversari:
            # Il calendario c'e' ma la sua squadra non gioca: turno di riposo,
            # o un giocatore rimasto in rosa dopo un trasferimento fuori dalla
            # Serie A. In tutti e due i casi domenica non porta niente.
            gioca, nota = 0.0, "non gioca questa giornata"
        schierabili.append(
            Schierato(
                valutazione=v,
                gioca=gioca,
                rende=rendimento_atteso(v, forma.get(acquisto.id_fc), contro),
                nota=nota,
                avversario=contro,
            )
        )
    schierabili.sort(key=lambda s: -s.punti)
    return schierabili


def _bonus_modificatore(portiere: Schierato | None, difesa: list[Schierato]) -> float:
    """Quanto aggiunge la media voto del reparto arretrato.

    Si calcola sui voti ATTESI e non sui punti: il modificatore premia chi non
    prende gol, non chi ne segna, ed e' l'unica parte del fantacalcio in cui un
    difensore da 6,5 fisso vale piu' di uno da 6 che ogni tanto segna.
    """
    dentro = ([portiere] if portiere else []) + difesa[:DIFENSORI_NEL_MODIFICATORE]
    if not dentro:
        return 0.0
    media = sum(s.valutazione.media_voto_attesa for s in dentro) / len(dentro)
    return PESO_MODIFICATORE * (media - VOTO_NEUTRO)


def consiglia(
    stato: StatoAsta,
    squadra: Squadra,
    forma: dict[int, float] | None = None,
    avversari: dict[str, Avversario] | None = None,
) -> Consiglio | None:
    """Il modulo e gli undici che rendono di piu', fra quelli che puoi fare."""
    rosa = valuta_per_domenica(stato, squadra, forma, avversari)
    if not rosa:
        return None
    per_ruolo: dict[str, list[Schierato]] = {r: [] for r in ("p", "d", "c", "a")}
    for s in rosa:
        if s.ruolo in per_ruolo:
            per_ruolo[s.ruolo].append(s)

    portiere = per_ruolo["p"][0] if per_ruolo["p"] else None
    migliore: Consiglio | None = None
    for modulo in MODULI:
        quanti = dict(zip(("d", "c", "a"), modulo, strict=True))
        if any(len(per_ruolo[r]) < n for r, n in quanti.items()):
            continue
        titolari = [portiere] if portiere else []
        for ruolo, n in quanti.items():
            titolari.extend(per_ruolo[ruolo][:n])
        punti = sum(s.punti for s in titolari)
        if stato.parametri.modificatore_difesa:
            difesa = sorted(
                per_ruolo["d"][: quanti["d"]],
                key=lambda s: -s.valutazione.media_voto_attesa,
            )
            punti += _bonus_modificatore(portiere, difesa)
        if migliore is None or punti > migliore.punti:
            schierati = {id(s) for s in titolari}
            migliore = Consiglio(
                modulo=modulo,
                titolari=titolari,
                panchina=[s for s in rosa if id(s) not in schierati],
                punti=punti,
            )

    if migliore is None:
        return None
    return Consiglio(
        modulo=migliore.modulo,
        titolari=migliore.titolari,
        panchina=migliore.panchina,
        punti=migliore.punti,
        avvisi=_avvisi(migliore, per_ruolo),
    )


def _avvisi(c: Consiglio, per_ruolo: dict[str, list[Schierato]]) -> list[str]:
    """Le cose che il numero da solo non dice, e che cambierebbero la scelta."""
    avvisi: list[str] = []
    if not per_ruolo["p"]:
        avvisi.append("Non hai nessun portiere in rosa.")
    dubbi = [s for s in c.titolari if 0 < s.gioca < 0.7]
    if dubbi:
        nomi = ", ".join(f"{s.nome} ({s.nota})" for s in dubbi[:4])
        avvisi.append(f"Schierati ma non sicuri: {nomi}.")
    # Una panchina di gente che non gioca non e' una panchina: se il titolare
    # non prende voto, non subentra nessuno.
    coperture = [s for s in c.panchina if s.gioca >= 0.6]
    if len(coperture) < 2:
        avvisi.append(
            "La panchina non copre: se un titolare resta senza voto, "
            "non c'e' nessuno che gioca davvero a sostituirlo."
        )
    return avvisi


# --- gli scambi ----------------------------------------------------------


@dataclass(frozen=True)
class Scambio:
    """Uno scambio uno-a-uno che conviene a me, e che l'altro puo' accettare."""

    do: Valutazione
    prendo: Valutazione
    con: Squadra
    guadagno: float  # valore che guadagno io
    suo_guadagno: float  # valore che guadagna lui, con i suoi buchi


def _bisogno(stato: StatoAsta, squadra: Squadra) -> dict[str, float]:
    """Quanto manca a ogni reparto, misurato in valore e non in slot.

    Uno slot vuoto non e' un bisogno: e' un bisogno solo se quello che c'e'
    dentro rende poco. Una squadra con otto difensori mediocri ha bisogno di
    difensori quanto una che ne ha sei.
    """
    per_ruolo: dict[str, list[float]] = {}
    for a in squadra.acquisti:
        v = stato.valutazioni.get(a.id_fc)
        if v is not None:
            per_ruolo.setdefault(a.ruolo, []).append(v.valore)
    bisogni: dict[str, float] = {}
    for ruolo in RUOLI_DELLA_DIFESA + ("c", "a"):
        valori = sorted(per_ruolo.get(ruolo, []), reverse=True)
        titolari = max(1, round(TITOLARI_PER_RUOLO.get(ruolo, 3)))
        schierati = valori[:titolari]
        # Il bisogno e' quanto e' debole il PEGGIORE dei titolari: e' quello
        # che uno scambio sostituirebbe davvero.
        bisogni[ruolo] = -(min(schierati) if schierati else 0.0)
    return bisogni


TITOLARI_PER_RUOLO = {"p": 1, "d": 4, "c": 4, "a": 2}


def scambi_possibili(
    stato: StatoAsta, squadra: Squadra, limite: int = 6
) -> list[Scambio]:
    """Gli scambi uno-a-uno che migliorano me senza essere assurdi per l'altro.

    UNO SCAMBIO SI PROPONE, NON SI IMPONE: uno che conviene solo a me non e'
    uno scambio, e' una lista dei desideri. Per questo si tiene solo quello che
    alza il valore di ENTRAMBE le rose — cosa possibile perche' le rose hanno
    buchi diversi, e lo stesso centrocampista vale piu' a chi ne ha tre scarsi
    che a chi ne ha otto buoni.

    Restano fuori dal conto due cose che il bot non sa: la simpatia e il
    rancore. Il consiglio dice quali scambi hanno senso sui numeri; se poi
    quello e' l'avversario che non ti parla da marzo, lo sai tu.
    """
    miei = [
        (a, stato.valutazioni[a.id_fc])
        for a in squadra.acquisti
        if a.id_fc in stato.valutazioni
    ]
    if not miei:
        return []
    mio_bisogno = _bisogno(stato, squadra)

    proposte: list[Scambio] = []
    for altra in stato.squadre:
        if altra.id == squadra.id:
            continue
        suo_bisogno = _bisogno(stato, altra)
        suoi = [
            (a, stato.valutazioni[a.id_fc])
            for a in altra.acquisti
            if a.id_fc in stato.valutazioni
        ]
        for _, mio in miei:
            for _, suo in suoi:
                if mio.giocatore.ruolo == suo.giocatore.ruolo:
                    # Stesso ruolo: e' solo un confronto di valore, e chi
                    # perde non ha nessuna ragione di accettare.
                    continue
                # Io guadagno il valore di chi prendo meno quello di chi do,
                # pesato da quanto mi serve quel reparto. Lui, specularmente.
                mio_guadagno = (
                    suo.valore
                    + mio_bisogno.get(suo.giocatore.ruolo, 0.0)
                    - mio.valore
                    - mio_bisogno.get(mio.giocatore.ruolo, 0.0)
                )
                suo_guadagno = (
                    mio.valore
                    + suo_bisogno.get(mio.giocatore.ruolo, 0.0)
                    - suo.valore
                    - suo_bisogno.get(suo.giocatore.ruolo, 0.0)
                )
                if mio_guadagno <= 0 or suo_guadagno <= 0:
                    continue
                proposte.append(
                    Scambio(
                        do=mio,
                        prendo=suo,
                        con=altra,
                        guadagno=mio_guadagno,
                        suo_guadagno=suo_guadagno,
                    )
                )
    # Prima quelli che convengono di piu' a me, ma a parita' quelli che
    # convengono di piu' anche a lui: sono quelli che vengono accettati.
    proposte.sort(key=lambda s: (-s.guadagno, -s.suo_guadagno))
    return proposte[:limite]


# --- gli abbinamenti di calendario ---------------------------------------


# Come si compone l'attacco, e non e' una regola del bot: e' la regola di chi
# gioca. Un Top si abbina a un Semi-Top e una Terza fascia a una Quarta —
# perche' due Top costano mezzo budget e due Quarte non fanno una domenica.
# La coppia bilanciata e' quella che tiene insieme il tetto e il pavimento.
FASCE_ABBINABILI: dict[str, tuple[tuple[int, int], ...]] = {
    "a": ((1, 2), (3, 4)),
}


def fascia_di(v: Valutazione) -> int:
    """La fascia da usare per le regole di composizione.

    Prima quella del listino esterno, che e' come le chiama chi ha scritto la
    strategia ("Top", "Semi-Top"); solo se manca si ripiega su quella che il
    motore calcola dal FVM. Le due quasi coincidono, ma quando la regola e'
    detta a parole va rispettata con le parole di chi l'ha detta.
    """
    j = v.giocatore.giudizi
    if j is not None and j.fascia:
        return j.fascia
    return v.fascia


@dataclass(frozen=True)
class Abbinamento:
    """Due giocatori di due squadre che si alternano bene sul calendario."""

    primo: Valutazione
    secondo: Valutazione
    punteggio: int
    costo: float
    valore: float

    @property
    def squadre(self) -> tuple[str, str]:
        return (self.primo.giocatore.squadra, self.secondo.giocatore.squadra)

    @property
    def fasce(self) -> tuple[int, int]:
        return (fascia_di(self.primo), fascia_di(self.secondo))


def _rappresentanti(
    stato: StatoAsta, ruolo: str, liberi_soltanto: bool, per_fascia: bool
) -> dict[str, list[Valutazione]]:
    """Chi rappresenta ogni squadra in un abbinamento.

    SI SCEGLIE PER MINUTI, NON PER VALORE, e la differenza si e' vista subito:
    nel ruolo del portiere le valutazioni si schiacciano tutte su cifre vicine,
    e ordinando per valore il Genoa era rappresentato da Sommariva — zero
    minuti — invece che da Bijlow, che li ha giocati tutti. L'abbinamento
    usciva a due crediti e non voleva dire niente, perche' quei due portieri in
    campo non ci vanno. Un abbinamento di calendario ha senso solo fra chi il
    calendario lo gioca.

    UNO PER SQUADRA O UNO PER FASCIA, e dipende dal ruolo. Di portieri se ne
    schiera uno e uno solo rappresenta il suo club. In attacco no: la Roma ha
    un Top e un Semi-Top, e tenerne uno solo cancellava meta' delle coppie
    possibili — Malen spariva dietro Dybala, che e' un'altra fascia e un'altra
    domanda.
    """
    scelti: dict[str, dict[int, Valutazione]] = {}

    def quanto_gioca(v: Valutazione) -> tuple[float, float]:
        campo = v.giocatore.campo
        return (campo.quota_minuti if campo is not None else 0.0, v.valore)

    fonte = stato.disponibili() if liberi_soltanto else stato.in_gioco()
    for v in fonte:
        if v.giocatore.ruolo != ruolo:
            continue
        sigla = v.giocatore.squadra
        chiave = fascia_di(v) if per_fascia else 0
        dentro = scelti.setdefault(sigla, {})
        if chiave not in dentro or quanto_gioca(v) > quanto_gioca(dentro[chiave]):
            dentro[chiave] = v
    return {sigla: list(per_chiave.values()) for sigla, per_chiave in scelti.items()}


def abbinamenti(
    stato: StatoAsta,
    tabella: dict[tuple[str, str], int],
    ruolo: str = "p",
    *,
    limite: int = 8,
    insieme_a: str | None = None,
    partendo_da: Valutazione | None = None,
    liberi_soltanto: bool = True,
    fasce: tuple[int, int] | None = None,
) -> list[Abbinamento]:
    """Le coppie migliori, tradotte in giocatori veri con i loro prezzi.

    `insieme_a` e' la sigla di una squadra che hai gia' in rosa: da quel
    momento la domanda non e' piu' "qual e' la coppia migliore" ma "chi si
    abbina meglio a quello che ho", che e' l'unica che si puo' ancora
    rispondere a meta' asta.

    `partendo_da` e' il giocatore che hai gia' comprato, ed e' la forma che
    serve davvero all'asta: non "la Roma con chi sta bene" ma "ho Malen, adesso
    chi ci metto accanto". Fissa un lato della coppia su quella persona, non
    sul suo club — la Roma ha anche Dybala, che e' un'altra fascia e un'altra
    domanda.

    `fasce` impone la composizione: `(1, 2)` cerca un Top con un Semi-Top,
    `(3, 4)` una Terza con una Quarta. In attacco non e' un di piu' — due Top
    costano mezzo budget e due Quarte non fanno una domenica.
    """
    candidati = _rappresentanti(
        stato, ruolo, liberi_soltanto, per_fascia=fasce is not None
    )
    if partendo_da is not None:
        # Il giocatore che ho gia' comprato non e' fra i liberi, e deve
        # rappresentare il suo club da solo: e' lui quello da completare.
        insieme_a = partendo_da.giocatore.squadra
        candidati[insieme_a] = [partendo_da]
    esito: list[Abbinamento] = []
    for (a, b), voto in tabella.items():
        if insieme_a is not None and insieme_a not in (a, b):
            continue
        for primo in candidati.get(a, ()):
            for secondo in candidati.get(b, ()):
                coppia = (primo, secondo)
                if fasce is not None:
                    # La coppia vale in un verso o nell'altro: la tabella non
                    # ha un sopra e un sotto, e neanche le fasce.
                    trovate = (fascia_di(primo), fascia_di(secondo))
                    if sorted(trovate) != sorted(fasce):
                        continue
                    if trovate != fasce:
                        coppia = (secondo, primo)
                esito.append(
                    Abbinamento(
                        primo=coppia[0],
                        secondo=coppia[1],
                        punteggio=voto,
                        costo=coppia[0].prezzo_mercato + coppia[1].prezzo_mercato,
                        valore=coppia[0].valore + coppia[1].valore,
                    )
                )
    # Prima il calendario, che e' quello che la tabella misura; a parita', chi
    # costa meno — fra due coppie ugualmente buone si prende quella che lascia
    # crediti per il resto della rosa.
    esito.sort(key=lambda x: (-x.punteggio, x.costo))
    return esito[:limite]
