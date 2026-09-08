"""L'asta mentre succede: chi resta, quanto costa adesso, fino a quanto spingere.

Il listino calcolato prima dell'asta invecchia al terzo giocatore chiamato. Se
i primi big vanno via a poco, in sala restano crediti che *devono* essere
spesi: tutto il resto vale di piu'. Se vanno via a cifre folli, chi non ha
ancora comprato si ritrova con meno soldi e i prezzi crollano. Questo modulo
ricalcola il mercato dopo ogni assegnazione, e da li' ricava la sola cosa che
serve davvero mentre l'asta corre: **fino a quanto posso offrire per questo
giocatore, adesso.**

Le tre spinte che alzano o abbassano l'offerta rispetto al prezzo corrente:

* **convenienza** - quanto il giocatore vale piu' di quanto costa;
* **agio** - quanti crediti ho io per slot rispetto alla media della lega:
  chi e' piu' ricco degli altri *deve* offrire di piu', i crediti avanzati a
  fine asta non valgono niente;
* **urgenza** - quanti giocatori sopra il livello di rimpiazzo restano nel
  ruolo che devo ancora riempire.

E i due tetti che non si superano mai, qualunque cosa dicano le spinte:
tenere un credito per ogni slot ancora vuoto, e tenere abbastanza da non
finire l'asta con un buco al posto di un reparto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .valutazione import RUOLI, ParametriLega, Valutazione, pesi_prezzo

# I limiti entro cui le spinte possono muovere l'offerta rispetto al prezzo
# corrente di mercato. Senza un tetto, un modello sicuro di se' porta a
# spendere meta' budget sul primo nome che gli piace.
SPINTA_MINIMA = 0.70
SPINTA_MASSIMA = 1.80

# Quanta strada percorrere verso il valore stimato, quando supera il prezzo
# corrente. Meta': il valore e' un modello, il prezzo e' quello che gli altri
# fanno davvero.
QUOTA_VERSO_IL_VALORE = 0.5

# Quanto la tua lista sposta l'offerta. Un obiettivo dichiarato deve pesare
# abbastanza da vincere un testa a testa, non tanto da far saltare il budget.
GRADO_MAI = -2
PESO_PREFERENZA = {2: 1.35, 1: 1.15, 0: 1.0, -1: 0.75, GRADO_MAI: 0.0}

# Quante assegnazioni servono prima di credere a quello che l'asta dice
# sulla forma del mercato, e quanto le si concede di piegare la curva.
ACQUISTI_PER_STIMARE_LA_CURVA = 10
PENDENZA_MINIMA = 0.75
PENDENZA_MASSIMA = 1.60

# Quando un'esca e' un'esca. Sotto i cinque crediti non drena niente e il giro
# lo hai speso per niente; e con un solo rivale interessato non c'e' rilancio,
# c'e' un regalo — quello lo prende alla base e ringrazia.
ESCA_PREZZO_MINIMO = 5.0
ESCA_RIVALI_MINIMI = 2


@dataclass(frozen=True)
class Acquisto:
    id_fc: int
    nome: str
    ruolo: str
    id_squadra: int
    prezzo: int


@dataclass
class Squadra:
    id: int
    nome: str
    e_mia: bool = False
    acquisti: list[Acquisto] = field(default_factory=list)

    def spesa(self) -> int:
        return sum(a.prezzo for a in self.acquisti)

    def presi_per_ruolo(self, ruolo: str) -> int:
        return sum(1 for a in self.acquisti if a.ruolo == ruolo)


@dataclass(frozen=True)
class Rivale:
    """Un avversario che puo' ancora contendermi un giocatore, e fino a quanto."""

    squadra: Squadra
    massimo: int


@dataclass(frozen=True)
class Esca:
    """Un giocatore da chiamare per far spendere gli altri, non per prenderlo.

    `drenati` e' quanto uscira' dalle tasche di chi se lo prende. `rischio` e'
    quanto costa a te se nessuno rilancia — che e' il prezzo base, uno, e va
    detto sempre: un'esca e' una scommessa piccola, ma e' una scommessa.
    """

    valutazione: Valutazione
    prezzo_corrente: float
    drenati: int
    rivali: tuple[Rivale, ...]
    slot_libero: bool

    @property
    def nome(self) -> str:
        return self.valutazione.giocatore.nome

    @property
    def rischio(self) -> str:
        """Cosa succede se non rilancia nessuno."""
        if self.slot_libero:
            return "se nessuno rilancia te lo prendi a 1: hai lo slot libero"
        return "hai il reparto pieno: se nessuno rilancia non puoi prenderlo"


@dataclass(frozen=True)
class Consiglio:
    """La risposta a "quanto offro?", con il perche' accanto."""

    valutazione: Valutazione
    massimo: int
    prezzo_corrente: float
    giudizio: str
    motivi: tuple[str, ...]
    tetto_liquidita: int
    convenienza: float
    agio: float
    urgenza: float
    # Chi puo' ancora contendertelo, e la cifra che dovrebbe bastare per
    # portarlo a casa: in un'asta a rilancio si paga il secondo offerente
    # piu' uno, non il proprio limite.
    rivali: tuple[Rivale, ...] = ()
    serve: int = 1
    preferenza: int = 0

    @property
    def guadagno(self) -> float:
        """Crediti di valore che porti a casa se lo prendi alla cifra che serve."""
        return self.valutazione.valore - self.serve


class StatoAsta:
    """La fotografia dell'asta in questo momento.

    Si costruisce da capo a ogni comando del bot: costa pochi millisecondi su
    seicento giocatori e non c'e' nessuno stato da tenere allineato a mano,
    che durante un'asta e' esattamente il tipo di bug che non ti accorgi di
    avere finche' non hai gia' comprato.
    """

    def __init__(
        self,
        parametri: ParametriLega,
        valutazioni: dict[int, Valutazione],
        squadre: list[Squadra],
        preferenze: dict[int, int] | None = None,
        prezzi_osservati: dict[int, float] | None = None,
    ) -> None:
        self.parametri = parametri
        self.valutazioni = valutazioni
        self.squadre = squadre
        self.preferenze = preferenze or {}
        # Gli stessi prezzi veri che hanno formato le valutazioni: senza,
        # il listino importato spariva appena l'asta cominciava, perche' il
        # prezzo corrente si ricalcolava dalla sola stima.
        self.prezzi_osservati = prezzi_osservati or {}
        self.presi: dict[int, Squadra] = {
            a.id_fc: s for s in squadre for a in s.acquisti
        }
        self._prezzi_correnti: dict[int, float] | None = None
        self._disponibili: list[Valutazione] | None = None
        self._pendenza: float | None = None

    def invalida(self) -> None:
        """Da chiamare se si modificano le rose senza ricostruire lo stato.

        Normalmente non serve: il bot ricostruisce lo stato da zero a ogni
        messaggio, ed e' il motivo per cui i conti non possono andare fuori
        sincrono. Serve a chi costruisce scenari - i test e le simulazioni.
        """
        self._prezzi_correnti = None
        self._disponibili = None
        self._pendenza = None

    # -- lo stato delle squadre ------------------------------------------

    @property
    def mia(self) -> Squadra | None:
        return next((s for s in self.squadre if s.e_mia), None)

    def crediti_residui(self, squadra: Squadra) -> int:
        return self.parametri.crediti - squadra.spesa()

    def slot_mancanti(self, squadra: Squadra) -> dict[str, int]:
        return {
            r: max(0, self.parametri.slot[r] - squadra.presi_per_ruolo(r))
            for r in RUOLI
        }

    def slot_mancanti_totali(self, squadra: Squadra) -> int:
        return sum(self.slot_mancanti(squadra).values())

    def slot_mancanti_lega(self) -> dict[str, int]:
        totali = {r: 0 for r in RUOLI}
        for s in self.squadre:
            for r, n in self.slot_mancanti(s).items():
                totali[r] += n
        return totali

    # -- di chi e' il turno ----------------------------------------------

    def puo_chiamare(self, squadra: Squadra, ruolo: str | None = None) -> bool:
        """Se questa squadra puo' ancora chiamare, e per quel reparto.

        Due condizioni, e servono entrambe: uno slot libero dove metterlo, e
        almeno un credito per offrire. Una squadra con la rosa piena e una con
        zero crediti sono ugualmente fuori dal giro, ed e' il momento in cui
        smettono di far salire i prezzi — cioe' il momento in cui conviene
        chiamare quello che si vuole davvero.
        """
        if self.crediti_residui(squadra) < 1:
            return False
        mancanti = self.slot_mancanti(squadra)
        if ruolo:
            return mancanti.get(ruolo, 0) > 0
        return any(n > 0 for n in mancanti.values())

    def chi_chiama(self, turno: int, reparto: str | None = None) -> Squadra | None:
        """Chi ha il turno adesso, saltando chi non puo' piu' chiamare.

        Il salto non e' una cortesia: e' la regola. Chi ha completato quel
        reparto passa la mano, e chi tiene il conto a mano se ne dimentica
        esattamente quando conta — a reparto quasi chiuso, quando ogni giro
        saltato e' un giocatore che arriva a prezzo di base.
        """
        if not self.squadre:
            return None
        n = len(self.squadre)
        for salto in range(n):
            candidata = self.squadre[(turno + salto) % n]
            if self.puo_chiamare(candidata, reparto):
                return candidata
        return None

    def prossimo_turno(self, turno: int, reparto: str | None = None) -> int:
        """L'indice di chi chiamera' dopo di me."""
        if not self.squadre:
            return 0
        n = len(self.squadre)
        for salto in range(1, n + 1):
            if self.puo_chiamare(self.squadre[(turno + salto) % n], reparto):
                return (turno + salto) % n
        return (turno + 1) % n

    def chi_cerca(self, ruolo: str) -> list[Squadra]:
        """Le squadre che hanno ancora bisogno di quel ruolo, e i crediti."""
        return [s for s in self.squadre if self.puo_chiamare(s, ruolo)]

    def reparti_solo_miei(self) -> list[str]:
        """I ruoli che nessun altro cerca piu': li' il prezzo lo fai tu.

        E' la situazione che vale piu' crediti di tutta l'asta e passa
        inosservata, perche' succede mentre si guarda un altro giocatore. Da
        quel momento ogni chiamata in quel reparto si chiude alla base, e
        conviene prendere i migliori rimasti invece dei piu' economici.
        """
        mia = self.mia
        if mia is None:
            return []
        soli = []
        for ruolo in RUOLI:
            if not self.puo_chiamare(mia, ruolo):
                continue
            if all(s.e_mia for s in self.chi_cerca(ruolo)):
                soli.append(ruolo)
        return soli

    def disponibili(self) -> list[Valutazione]:
        """Chi si puo' ancora chiamare.

        Due modi di non esserci, e vanno tolti tutti e due: chi e' gia' stato
        assegnato a una squadra, e chi non gioca piu' in Serie A. Il secondo
        il listone non lo sa — continua a elencarlo con la vecchia maglia — e
        finche' restava qui dentro faceva due danni in una volta: usciva fra i
        consigli, e si prendeva la sua fetta dei crediti nel calcolo dei
        prezzi, rendendo tutti gli altri piu' economici di quanto siano.
        """
        if self._disponibili is None:
            self._disponibili = [
                v
                for v in self.valutazioni.values()
                if v.giocatore.id_fc not in self.presi and v.giocatore.in_lista
            ]
        return self._disponibili

    def in_gioco(self) -> list[Valutazione]:
        """Tutti quelli che contano ancora: i liberi piu' quelli gia' presi.

        Serve dove si guarda anche alle rose altrui — gli abbinamenti fatti
        sulla lega intera, gli scambi — e dove quindi un giocatore assegnato
        va tenuto, ma uno che ha cambiato campionato no.
        """
        return [
            v
            for v in self.valutazioni.values()
            if v.giocatore.in_lista or v.giocatore.id_fc in self.presi
        ]

    # -- il mercato che cambia -------------------------------------------

    def prezzi_correnti(self) -> dict[int, float]:
        """Il prezzo di ogni giocatore ancora libero, ricalcolato adesso.

        Gli stessi crediti di prima meno quelli gia' spesi, da spartire fra i
        soli giocatori che entreranno ancora in una rosa. E' qui che vive
        l'inflazione d'asta, che a occhio nudo non si vede mai in tempo.
        """
        if self._prezzi_correnti is not None:
            return self._prezzi_correnti

        mancanti = self.slot_mancanti_lega()
        crediti_residui = sum(self.crediti_residui(s) for s in self.squadre)
        slot_residui = sum(mancanti.values())
        liberi = max(0.0, crediti_residui - slot_residui)

        # Chi entrera' ancora in una rosa: i migliori per FVM di ogni ruolo,
        # tanti quanti gli slot ancora scoperti in quel ruolo.
        mercato = []
        for ruolo in RUOLI:
            candidati = sorted(
                (v for v in self.disponibili() if v.giocatore.ruolo == ruolo),
                key=lambda v: (-v.giocatore.fvm, -v.giocatore.quota),
            )
            mercato.extend(v.giocatore for v in candidati[: mancanti[ruolo]])

        # La forma della curva la detta la tua lega, non il listino: se qui i
        # big si pagano piu' di quanto dice il listone, i pesi vanno resi piu'
        # ripidi prima di spartire i crediti.
        pendenza = self.pendenza_di_mercato()
        pesi = {
            id_fc: peso**pendenza
            for id_fc, peso in pesi_prezzo(mercato, self.prezzi_osservati).items()
        }
        totale = sum(pesi.values())
        prezzi = {}
        for v in self.disponibili():
            peso = pesi.get(v.giocatore.id_fc)
            prezzi[v.giocatore.id_fc] = (
                1.0 + liberi * peso / totale
                if peso is not None and totale > 0
                else 1.0
            )
        self._prezzi_correnti = prezzi
        return prezzi

    def pendenza_di_mercato(self) -> float:
        """Quanto la tua lega e' piu' ripida del listino, misurata sull'asta stessa.

        Ogni tavolo ha un carattere: da qualche parte i campioni si pagano
        molto sopra il listino e la fascia media si svende, altrove i crediti
        si spalmano. E' un fatto che nessun listone puo' sapere in anticipo -
        ma dopo una decina di chiamate l'asta lo ha gia' scritto da sola.

        Si confronta quello che e' stato pagato con quello che il listino
        prevedeva, in scala logaritmica: una pendenza di 1 vuol dire un
        mercato fedele al listino, 1.3 che i big vanno molto piu' cari di
        quanto dovrebbero, 0.8 che i crediti si stanno spalmando.

        Sotto le dieci assegnazioni non si stima niente: due nomi pagati a
        casaccio darebbero una curva ripidissima e sballerebbero tutti i
        prezzi a inizio asta, che e' il momento in cui servono giusti.
        """
        if self._pendenza is not None:
            return self._pendenza
        punti: list[tuple[float, float, float]] = []
        for squadra in self.squadre:
            for a in squadra.acquisti:
                v = self.valutazioni.get(a.id_fc)
                if v is None or v.prezzo_mercato < 2 or a.prezzo < 1:
                    continue
                punti.append(
                    (math.log(v.prezzo_mercato), math.log(a.prezzo), 1.0)
                )
        if len(punti) < ACQUISTI_PER_STIMARE_LA_CURVA:
            self._pendenza = 1.0
            return 1.0
        media_x = sum(x for x, _, _ in punti) / len(punti)
        media_y = sum(y for _, y, _ in punti) / len(punti)
        sxx = sum((x - media_x) ** 2 for x, _, _ in punti)
        sxy = sum((x - media_x) * (y - media_y) for x, y, _ in punti)
        grezza = sxy / sxx if sxx > 1e-9 else 1.0
        self._pendenza = min(max(grezza, PENDENZA_MINIMA), PENDENZA_MASSIMA)
        return self._pendenza

    def inflazione(self) -> float:
        """Quanto il mercato e' piu' caro (>1) o piu' a buon prezzo (<1) di inizio asta.

        Un solo numero, e vale tutta l'asta: sopra 1.15 stai per pagare tutto
        troppo e conviene aspettare; sotto 0.9 e' il momento di alzare la mano.
        """
        correnti = self.prezzi_correnti()
        disponibili = [v for v in self.disponibili() if v.fascia < 5]
        iniziale = sum(v.prezzo_mercato for v in disponibili)
        adesso = sum(correnti.get(v.giocatore.id_fc, 1.0) for v in disponibili)
        return adesso / iniziale if iniziale > 0 else 1.0

    # -- la domanda che conta --------------------------------------------

    def tetto_liquidita(self, squadra: Squadra) -> int:
        """Il massimo assoluto: un credito va lasciato per ogni slot vuoto.

        Superarlo significa arrivare a fine asta con una casella che non puoi
        riempire, e una rosa incompleta prende zero in quel ruolo tutte le
        domeniche.
        """
        return max(
            0, self.crediti_residui(squadra) - (self.slot_mancanti_totali(squadra) - 1)
        )

    def tetto_reparti(self, squadra: Squadra, ruolo: str) -> int:
        """Il massimo che lascia ancora comprare qualcosa di decente altrove.

        Non basta poter riempire gli slot a un credito: se svuoti il portafogli
        sul terzo attaccante, i tuoi otto difensori li prendi tutti dal fondo
        del listone. La riserva e' quindi il costo dei giocatori **piu'
        economici che valgano ancora qualcosa** - quelli sopra il livello di
        rimpiazzo - non dei piu' economici e basta: mettere da parte il prezzo
        di venti riserve da un credito significa non mettere da parte niente.
        """
        correnti = self.prezzi_correnti()
        riserva = 0.0
        for altro in RUOLI:
            mancanti = self.slot_mancanti(squadra)[altro]
            if altro == ruolo:
                mancanti -= 1
            if mancanti <= 0:
                continue
            del_ruolo = [v for v in self.disponibili() if v.giocatore.ruolo == altro]
            validi = sorted(
                correnti.get(v.giocatore.id_fc, 1.0) for v in del_ruolo if v.vorp > 0
            )
            if len(validi) < mancanti:
                # Quando i giocatori validi sono finiti, il resto degli slot
                # costa quello che costa il fondo del listone: un credito.
                resto = sorted(
                    correnti.get(v.giocatore.id_fc, 1.0)
                    for v in del_ruolo
                    if v.vorp <= 0
                )
                validi = validi + resto
            riserva += sum(validi[:mancanti]) if validi else mancanti
        return max(0, int(self.crediti_residui(squadra) - riserva))

    def rivali(self, id_fc: int) -> list[Rivale]:
        """Chi puo' ancora contendermi questo giocatore, e fino a quanto.

        Un avversario e' fuori dai giochi per due motivi diversi e altrettanto
        definitivi: ha gia' completato quel reparto, oppure i crediti che gli
        restano non gli permettono di superarti. Saperlo cambia l'offerta piu'
        di qualunque statistica: contro nessun rivale si prende alla base
        d'asta, e alzare la mano a quaranta e' un regalo agli altri.
        """
        v = self.valutazioni.get(id_fc)
        if v is None or id_fc in self.presi:
            return []
        ruolo = v.giocatore.ruolo
        prezzo = self.prezzi_correnti().get(id_fc, v.prezzo_mercato)
        elenco = []
        for s in self.squadre:
            if s.e_mia or self.slot_mancanti(s)[ruolo] <= 0:
                continue
            # Fin dove puo' spingersi: i crediti che ha davvero, ma non oltre
            # quello che un avversario ragionevole paga per quel giocatore.
            tetto = self.tetto_liquidita(s)
            plausibile = int(min(tetto, prezzo * SPINTA_MASSIMA))
            if plausibile >= 1:
                elenco.append(Rivale(squadra=s, massimo=plausibile))
        elenco.sort(key=lambda r: -r.massimo)
        return elenco

    def serve_per_vincere(self, id_fc: int) -> int:
        """La cifra che dovrebbe bastare per portarlo a casa.

        Due cose la determinano, e vince la piu' bassa. Con la lega al
        completo il giocatore va via al suo prezzo di mercato, che e' gia' la
        stima di quanto verra' aggiudicato: basta superarlo di poco. Ma se chi
        te lo contende non ha i crediti per arrivarci, il prezzo lo fai tu, e
        allora conta solo il tetto del miglior rivale.

        Prendere il solo tetto dei rivali dava numeri gonfiati - dava per
        scontato che tutti spingessero al massimo teorico - e faceva offrire
        109 per un giocatore che ne costava 60.
        """
        v = self.valutazioni.get(id_fc)
        if v is None or id_fc in self.presi:
            return 1
        rivali = self.rivali(id_fc)
        if not rivali:
            return 1
        prezzo = self.prezzi_correnti().get(id_fc, v.prezzo_mercato)
        return max(1, min(int(round(prezzo)) + 1, rivali[0].massimo + 1))

    def consiglia(self, id_fc: int, prudenza: float = 1.0) -> Consiglio | None:
        """Fino a quanto offrire per questo giocatore, adesso."""
        v = self.valutazioni.get(id_fc)
        mia = self.mia
        if v is None or mia is None:
            return None

        ruolo = v.giocatore.ruolo
        correnti = self.prezzi_correnti()
        prezzo = correnti.get(id_fc, v.prezzo_mercato)
        motivi: list[str] = []

        # 1. Convenienza: quanto vale rispetto a quanto costa adesso.
        convenienza = v.valore / max(prezzo, 1.0)
        if convenienza >= 1.25:
            motivi.append(f"rende il {(convenienza - 1) * 100:.0f}% piu' di quanto costa")
        elif convenienza <= 0.8:
            troppo = (1 / max(convenienza, 0.01) - 1) * 100
            motivi.append(f"costa il {troppo:.0f}% piu' di quanto rende")

        # 2. Agio: i crediti che ho per slot, contro quelli che hanno gli altri.
        agio = self._agio(mia)
        if agio >= 1.15:
            motivi.append("hai piu' crediti per slot della media: puoi alzare")
        elif agio <= 0.85:
            motivi.append("hai meno crediti per slot della media: stringi")

        # 3. Urgenza: quanti giocatori validi restano nel ruolo per gli slot
        #    che la lega deve ancora riempire.
        urgenza = self._urgenza(ruolo)
        if urgenza >= 1.15:
            motivi.append(f"i {self._nome_ruolo(ruolo)} buoni stanno finendo")

        # 4. Quanto lo vuoi tu, che il modello non puo' sapere. Una lista di
        #    obiettivi serve solo se sposta davvero le offerte.
        preferenza = self.preferenze.get(id_fc, 0)
        spinta_voluta = PESO_PREFERENZA.get(preferenza, 1.0)
        if preferenza > 0:
            motivi.append("e' nella tua lista: offro piu' del dovuto per averlo")
        elif preferenza < 0:
            motivi.append("lo hai messo tra quelli da evitare")

        spinta = min(
            SPINTA_MASSIMA,
            max(
                SPINTA_MINIMA,
                (0.55 + 0.45 * min(max(convenienza, 0.4), 2.0))
                * min(max(agio, 0.75), 1.35)
                * min(max(urgenza, 0.9), 1.3),
            ),
        ) * spinta_voluta
        teorico = prezzo * spinta
        # Il prezzo di mercato e' l'ancora, ma da solo non basta: un giocatore
        # che nessuno ha messo in lista costa 1 e resterebbe con un massimo di
        # 1, quando e' esattamente quello su cui conviene rilanciare. Quando
        # il valore supera l'ancora si concede meta' della distanza - meta' e
        # non tutta, perche' il valore e' una stima e il prezzo e' un fatto.
        if v.valore > teorico:
            teorico += (v.valore - teorico) * QUOTA_VERSO_IL_VALORE
        teorico /= max(prudenza, 0.5)

        tetto_liq = self.tetto_liquidita(mia)
        tetto_rep = self.tetto_reparti(mia, ruolo)
        massimo = int(math.floor(min(teorico, tetto_liq, tetto_rep)))
        massimo = max(0, massimo)

        if preferenza <= GRADO_MAI:
            massimo = 0
        if self.slot_mancanti(mia)[ruolo] <= 0:
            massimo = 0
            motivi.insert(0, f"il reparto {self._nome_ruolo(ruolo)} e' gia' completo")
        elif massimo <= 0:
            motivi.insert(0, "non hai i crediti per prenderlo e completare la rosa")
        elif massimo == tetto_rep < teorico:
            motivi.append("oltre questa cifra ti resterebbe troppo poco per gli altri reparti")
        elif massimo == tetto_liq < teorico:
            motivi.append("e' tutto quello che puoi offrire tenendo un credito per slot")

        rivali = self.rivali(id_fc)
        # Non si tronca al proprio massimo: se per averlo servono 150 e tu
        # arrivi a 105, la risposta utile e' "ti supereranno", non "offri 105".
        serve = self.serve_per_vincere(id_fc)
        if self.parametri.offerte_segrete and massimo > 0:
            # A buste chiuse non c'e' un secondo giro: chi offre la cifra che
            # "sarebbe bastata" scopre di aver perso il giocatore per un
            # credito, e non puo' rimediare. Si offre il proprio limite.
            serve = massimo
            motivi.insert(
                0, "offerta unica: qui si offre il proprio massimo, non uno di piu' del vicino"
            )
        if not rivali:
            motivi.insert(0, "nessun altro puo' prenderlo: parti dalla base e basta")
        elif len(rivali) == 1:
            motivi.insert(
                0,
                f"solo {rivali[0].squadra.nome} puo' contendertelo "
                f"(fino a {rivali[0].massimo})",
            )

        return Consiglio(
            valutazione=v,
            massimo=massimo,
            prezzo_corrente=prezzo,
            giudizio=self._giudizio(convenienza * agio, massimo),
            motivi=tuple(motivi),
            tetto_liquidita=tetto_liq,
            convenienza=convenienza,
            agio=agio,
            urgenza=urgenza,
            rivali=tuple(rivali),
            serve=max(1, serve),
            preferenza=preferenza,
        )

    # -- i pezzi del calcolo ---------------------------------------------

    def avanzamento(self) -> float:
        """Quanta asta e' gia' passata, da 0 a 1."""
        totali = self.parametri.slot_totali
        rimasti = sum(self.slot_mancanti_lega().values())
        return 1.0 - rimasti / totali if totali else 0.0

    def _agio(self, mia: Squadra) -> float:
        """Quanto sono ricco rispetto agli altri - pesato per quanta asta resta.

        Avere piu' crediti degli altri alla terza chiamata non e' un vantaggio:
        e' solo il fatto che non hai ancora comprato, e hai ancora venti slot
        per spenderli. Alla penultima chiamata e' un'altra cosa: quello che
        avanza vale zero, e chi non lo spende lo regala.

        Senza questa scala il bot si esaltava a inizio asta - vedeva gli altri
        gia' impegnati e consigliava di pagare un attaccante molto sopra il
        suo valore, quando c'era ancora tutto il mercato davanti.
        """
        miei_slot = max(1, self.slot_mancanti_totali(mia))
        miei = self.crediti_residui(mia) / miei_slot
        altre = [s for s in self.squadre if s is not mia]
        if not altre:
            return 1.0
        loro = [
            self.crediti_residui(s) / max(1, self.slot_mancanti_totali(s))
            for s in altre
        ]
        media = sum(loro) / len(loro)
        if media <= 0:
            return 1.0
        grezzo = miei / media
        return 1.0 + (grezzo - 1.0) * self.avanzamento()

    def _urgenza(self, ruolo: str) -> float:
        """Rapporto fra gli slot da riempire e i giocatori validi rimasti."""
        mancanti = self.slot_mancanti_lega()[ruolo]
        if mancanti <= 0:
            return 1.0
        validi = sum(
            1
            for v in self.disponibili()
            if v.giocatore.ruolo == ruolo and v.vorp > 0
        )
        if validi <= 0:
            return 1.3
        return min(1.3, max(0.9, mancanti / validi))

    @staticmethod
    def _nome_ruolo(ruolo: str) -> str:
        return {
            "p": "portieri",
            "d": "difensori",
            "c": "centrocampisti",
            "a": "attaccanti",
        }[ruolo]

    @staticmethod
    def _giudizio(convenienza: float, massimo: int) -> str:
        """La convenienza qui dentro e' gia' corretta per l'agio.

        Verso la fine, chi ha crediti in eccesso deve pagare sopra il valore:
        i crediti che restano in tasca a fine asta valgono zero, e un giudizio
        che lo ignorasse contraddirebbe la cifra scritta due righe sopra.
        """
        if massimo <= 0:
            return "lascialo"
        if convenienza >= 1.3:
            return "prendilo"
        if convenienza >= 1.0:
            return "vale il prezzo"
        if convenienza >= 0.8:
            return "solo se scende"
        return "lascialo"

    # -- cosa fare adesso -------------------------------------------------

    def occasioni(self, ruolo: str | None = None, limite: int = 10) -> list[Consiglio]:
        """I giocatori liberi che rendono piu' di quanto costeranno.

        Filtrati sui ruoli che mi mancano davvero: un difensore da urlo non
        serve a niente se ho gia' otto difensori.
        """
        mia = self.mia
        mancanti = self.slot_mancanti(mia) if mia else {r: 1 for r in RUOLI}
        consigli = []
        for v in self.disponibili():
            r = v.giocatore.ruolo
            if ruolo and r != ruolo:
                continue
            if not ruolo and mancanti.get(r, 0) <= 0:
                continue
            c = self.consiglia(v.giocatore.id_fc)
            if c and c.massimo > 0 and c.convenienza > 1.0:
                consigli.append(c)
        # Ordinati per quello che guadagni davvero: il valore meno la cifra
        # che serve a batterli tutti, non meno il prezzo di listino. Un
        # giocatore che vale 40 e ne costerebbe 30 non e' un affare se per
        # averlo devi arrivare a 38.
        consigli.sort(key=lambda c: c.guadagno, reverse=True)
        return consigli[:limite]

    def da_chiamare(self, limite: int = 6, reparto: str | None = None) -> list[Consiglio]:
        """Chi conviene chiamare adesso, in un'asta a chiamata libera.

        Chiamare e' una mossa, non un sorteggio: il momento giusto per il tuo
        obiettivo e' quando chi te lo contende ha gia' speso o ha gia' chiuso
        quel reparto. Qui si sommano le due cose - quanto ci guadagni e quanto
        pochi rivali restano - e si scarta chi ti costerebbe piu' del tuo
        stesso limite.
        """
        mia = self.mia
        if mia is None:
            return []
        mancanti = self.slot_mancanti(mia)
        candidati = []
        for v in self.disponibili():
            if reparto and v.giocatore.ruolo != reparto:
                continue
            if mancanti.get(v.giocatore.ruolo, 0) <= 0:
                continue
            c = self.consiglia(v.giocatore.id_fc)
            if c is None or c.massimo <= 0 or c.serve > c.massimo:
                continue
            if c.guadagno <= 0:
                continue
            # Meno rivali restano, piu' e' il momento: con due contendenti su
            # otto il prezzo lo fai tu.
            vantaggio = c.guadagno * (1 + 0.15 * (len(self.squadre) - 1 - len(c.rivali)))
            candidati.append((vantaggio, c))
        candidati.sort(key=lambda t: -t[0])
        return [c for _, c in candidati[:limite]]

    def reparto_aperto(self, da: str | None = None) -> str | None:
        """Il primo ruolo che qualcuno in lega deve ancora riempire.

        In un'asta che va a reparti si comincia dai portieri e si passa ai
        difensori quando **tutti** hanno finito i portieri, non quando ho
        finito io: finche' un solo avversario ha uno slot scoperto, quel
        reparto e' ancora in ballo e ci sono ancora crediti che si muovono li'.

        `da` dice da dove guardare: serve a non tornare indietro. Un reparto
        gia' chiuso non si riapre perche' qualcuno ha annullato un acquisto.
        """
        ordine = list(RUOLI)
        inizio = ordine.index(da) if da in ordine else 0
        for ruolo in ordine[inizio:]:
            if any(self.slot_mancanti(s).get(ruolo, 0) > 0 for s in self.squadre):
                return ruolo
        return None

    def esche(self, limite: int = 3, reparto: str | None = None) -> list[Esca]:
        """Chi chiamare per far spendere gli altri, quando non conviene comprare.

        E' la mossa che distingue un'asta giocata da un'asta subita. Quando
        tocca a te e i tuoi obiettivi costano troppo perche' gli avversari
        sono ancora pieni di crediti, la cosa peggiore e' chiamare quello che
        vuoi: lo paghi al massimo. La cosa migliore e' chiamare **quello che
        vogliono loro** — il mercato lo paga piu' di quanto vale, i crediti
        escono dalle loro tasche, e il tuo obiettivo fra due giri costa meno.
        """
        mia = self.mia
        if mia is None:
            return []
        mancanti = self.slot_mancanti(mia)
        prezzi = self.prezzi_correnti()
        trovate: list[Esca] = []
        for v in self.disponibili():
            ruolo = v.giocatore.ruolo
            if reparto and ruolo != reparto:
                continue
            # Non si usa come esca un giocatore che vuoi: il rischio e' che
            # nessuno rilanci e te lo porti a casa — con quello sarebbe un
            # regalo, non un rischio.
            if self.preferenze.get(v.giocatore.id_fc, 0) > 0:
                continue
            prezzo = prezzi.get(v.giocatore.id_fc, v.prezzo_mercato)
            if prezzo < ESCA_PREZZO_MINIMO:
                continue
            # DEVE COSTARE PIU' DI QUANTO VALE. Se e' un affare anche per te,
            # chiamarlo per farlo comprare a un altro e' regalargli un affare.
            if v.valore >= prezzo:
                continue
            rivali = [r for r in self.rivali(v.giocatore.id_fc) if r.massimo >= prezzo]
            if len(rivali) < ESCA_RIVALI_MINIMI:
                continue
            # Quanto esce dalle loro tasche: in un rilancio si paga il secondo
            # offerente piu' uno, quindi il conto lo fa il secondo, non il primo.
            drenati = min(rivali[1].massimo + 1, int(rivali[0].massimo))
            trovate.append(
                Esca(
                    valutazione=v,
                    prezzo_corrente=prezzo,
                    drenati=drenati,
                    rivali=tuple(rivali),
                    slot_libero=mancanti.get(ruolo, 0) > 0,
                )
            )
        trovate.sort(key=lambda e: -e.drenati)
        return trovate[:limite]

    def riepilogo(self, squadra: Squadra) -> dict[str, float]:
        """Come e' andata: spesa, valore comprato, e quanto sopra il rimpiazzo.

        Serve a fine asta e serve durante: `valore` e `speso` a confronto
        dicono se stai comprando bene o se ti stai solo svuotando le tasche.
        """
        valore = 0.0
        vorp = 0.0
        pagato_in_piu = 0.0
        for a in squadra.acquisti:
            v = self.valutazioni.get(a.id_fc)
            if v is None:
                continue
            valore += v.valore
            vorp += v.vorp
            pagato_in_piu += a.prezzo - v.valore
        return {
            "giocatori": len(squadra.acquisti),
            "speso": squadra.spesa(),
            "residui": self.crediti_residui(squadra),
            "valore": valore,
            "vorp": vorp,
            "scarto": -pagato_in_piu,
        }

    def piano_spesa(self) -> dict[str, int]:
        """Quanti crediti dovrei ancora destinare a ogni reparto.

        Non e' una regola aurea copiata da un forum: e' la spesa che il mercato
        corrente impone per riempire gli slot che mi restano, ruolo per ruolo.
        """
        mia = self.mia
        if mia is None:
            return {r: 0 for r in RUOLI}
        correnti = self.prezzi_correnti()
        mancanti = self.slot_mancanti(mia)
        grezzo: dict[str, float] = {}
        for ruolo in RUOLI:
            n = mancanti[ruolo]
            if n <= 0:
                grezzo[ruolo] = 0.0
                continue
            prezzi = sorted(
                (
                    correnti.get(v.giocatore.id_fc, 1.0)
                    for v in self.disponibili()
                    if v.giocatore.ruolo == ruolo
                ),
                reverse=True,
            )
            # Gli slot si riempiono con i migliori ancora liberi, non con la
            # media di tutti: quella e' la stima che fa restare i crediti in
            # tasca a fine asta.
            grezzo[ruolo] = sum(prezzi[:n]) if prezzi else float(n)
        totale = sum(grezzo.values())
        disponibili = self.crediti_residui(mia)
        if totale <= 0:
            return {r: 0 for r in RUOLI}
        return {
            r: int(round(disponibili * grezzo[r] / totale)) for r in RUOLI
        }
