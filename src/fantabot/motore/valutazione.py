"""Quanto vale davvero un giocatore, e quanto costera'.

Sono due numeri diversi e il bot li tiene separati apposta:

* **prezzo di mercato** - quanto lo pagherai in asta. Deriva dal FVM di
  fantacalcio.it, che e' gia' il consenso di mercato, normalizzato al budget
  della *tua* lega.
* **valore** - quanto rende a te. Deriva dai punti attesi in stagione,
  misurati **sopra il rimpiazzo**: un attaccante da 78 punti non vale 78, vale
  quanto supera l'attaccante che prenderesti gratis al suo posto.

Il margine sta nella differenza. Comprare al prezzo di mercato non fa vincere
nessuno: fa finire con la rosa che il listone aveva gia' scritto.

Nessuna costante inventata a mano lega il FVM al rendimento: la relazione e'
stimata ogni volta con una regressione pesata sui giocatori che hanno davvero
giocato, ruolo per ruolo. Se il mercato cambia, si adatta da solo.
"""

from __future__ import annotations

import math
from dataclasses import KW_ONLY, dataclass, field

RUOLI = ("p", "d", "c", "a")
NOMI_RUOLO = {
    "p": "Portiere",
    "d": "Difensore",
    "c": "Centrocampista",
    "a": "Attaccante",
}

# Quanti giocatori di quel ruolo scendono in campo in una giornata media,
# pesando i moduli piu' usati in Classic (3-4-3, 3-5-2, 4-4-2, 4-3-3).
# Serve a stabilire il livello di rimpiazzo: il primo che resta in panchina.
TITOLARI_MEDI = {"p": 1.0, "d": 3.5, "c": 4.0, "a": 2.5}

# Peso delle stagioni, dalla piu' recente: quella in corso, l'anno scorso,
# quello prima. Le prime due alla pari e la terza a meta': l'anno scorso
# conta, quello prima conferma.
#
# Che la stagione in corso pesi 1 come una intera NON vuol dire che pesi
# quanto una intera: i voti si pesano per presenze, e tre presenze contro
# trentaquattro valgono da sole il cinque per cento. Il peso cresce da solo
# giornata dopo giornata, senza che nessuno cambi questa riga a novembre.
PESI_STAGIONE = (1.0, 1.0, 0.55)

# Presenze pesate oltre le quali il passato e' un dato, non un aneddoto.
PRESENZE_PER_FIDARSI = 25.0
PRESENZE_PER_REGRESSIONE = 15.0

# Il tetto sul COEFFICIENTE stimato, contro una regressione rumorosa.
MASSIMO_EFFETTO_CLUB = 1.2

# Il tetto su quanto il cambio di maglia puo' spostare i voti, in punti di
# fantamedia. E' il vincolo che conta davvero: limitare il coefficiente non
# basta, perche' un salto di club abbastanza grande lo moltiplica comunque
# fino all'assurdo. Mezzo voto e' gia' tanto - il contesto conta, ma non
# riscrive il giocatore.
MASSIMO_SPOSTAMENTO_CLUB = 0.5

# Sotto questa dimensione di rosa non e' una squadra di Serie A ma un residuo
# del listone: una sigla con due giocatori dentro, che come "squadra piu'
# debole del campionato" falserebbe ogni confronto.
ROSA_MINIMA_PER_CONTARE = 12

# I ruoli che entrano nella media del modificatore di difesa.
RUOLI_DELLA_DIFESA = ("p", "d")

# --- Quanto credere a quello che si vede in campo -------------------------
#
# Le giornate gia' giocate sono l'unica cosa che dice se un giocatore giochera'
# davvero, e sono anche un campione piccolo: a settembre sono tre. Il peso
# cresce da solo con le giornate — a tre vale il 38%, a dieci il 67%, a
# stagione inoltrata quasi tutto — e non c'e' nessuna data da cambiare a mano.
#
# Il numero e' la meta' del campione: con tante giornate giocate quante ne dice
# questa riga, quello che si vede pesa quanto quello che si credeva prima.
#
# Tre per i giocatori di movimento, e non di piu', perche' i due lati della
# bilancia non sono alla pari: quanto si gioca e' la piu' persistente delle
# statistiche del calcio — chi e' fuori a settembre e' quasi sempre fuori a
# novembre — mentre il prior di agosto e' FVM piu' l'anno scorso, e l'anno
# scorso spesso e' stato in un'altra squadra. Milinkovic-Savic era il titolare
# del Torino, il che sul Napoli non dice niente.
#
# UNO PER I PORTIERI, e la differenza non e' un'opinione: e' come funziona il
# ruolo. Una squadra schiera un portiere e lo tiene in campo tutti e novanta i
# minuti, quindi nei suoi minuti non c'e' nessun turnover da confondere col
# segnale. Tre giornate a zero minuti per un centrocampista possono essere un
# fastidio muscolare; per un portiere vogliono dire che il titolare e' un
# altro, e aspettare a dirlo non e' prudenza — e' consigliare una riserva.
GIORNATE_PER_CREDERCI = {"p": 1.0, "d": 3.0, "c": 3.0, "a": 3.0}

# Sopra questi minuti a partita si e' titolari a tutti gli effetti. Serve a
# rendere confrontabili due cose che non lo sono: le presenze contano uguale
# chi gioca novanta minuti e chi entra all'85', e sulle sole presenze un
# subentrante fisso risulta titolare fisso.
MINUTI_DA_TITOLARE = 60.0

# Chi e' nell'undici previsto della prossima giornata vale almeno questo,
# qualunque cosa dicano i minuti passati. E' l'unico modo di vedere un
# titolare che rientra da un infortunio: nei minuti e' identico a una riserva,
# e senza questa riga il segnale che vale di piu' sarebbe l'unico che manca.
#
# ASIMMETRICO APPOSTA. Essere previsto titolare alza; NON esserlo non abbassa,
# perche' e' una previsione sola e il turnover e' normale — mentre i minuti
# giocati, che la rotazione la contengono gia', quella riserva la vedono.
QUOTA_DA_PREVISTO = 0.70

# Quanto conta l'osservazione sui minuti quando di quel giocatore sappiamo che
# e' infortunato. Poco: i suoi zero minuti non dicono piu' niente sulla sua
# gerarchia, la spiegazione ce l'abbiamo gia'. Non zero, perche' un infortunio
# lungo e' comunque una notizia cattiva.
PESO_CAMPO_SE_FERMO = 0.30

# --- I giudizi da 1 a 5 di un listino esterno -----------------------------
#
# FantaLab pubblica per ogni giocatore TITOLARITA', INTEGRITA' e AFFIDABILITA'
# da 1 a 5. La prima e' esattamente la quantita' che questo modulo fatica di
# piu' a stimare — quante partite giochera' — detta da chi il campionato lo
# guarda e sa gia' del mercato estivo e della gerarchia decisa in ritiro,
# mentre il FVM e lo storico quelle due cose non le contengono.
#
# Quante presenze vale ogni gradino. Non e' una calibrazione: e' la lettura
# delle parole che FantaLab usa accanto ai numeri ("titolarissimo" e' 5,
# "ballottaggio" un 3, "chiuso" un 1), riportata su trentotto giornate.
PRESENZE_DA_TITOLARITA = {5: 33.0, 4: 27.0, 3: 20.0, 2: 12.0, 1: 5.0}

# Quanto pesa quel giudizio contro il prior che il bot si e' fatto da solo.
# Meta' e meta': e' un'opinione, ma e' un'opinione informata su QUESTA
# stagione, mentre il prior del bot e' costruito su quelle passate. Quello che
# succede in campo li supera comunque entrambi, giornata dopo giornata.
PESO_TITOLARITA = 0.5

# L'integrita' e' la propensione a farsi male, e nei minuti giocati non si
# vede finche' non e' successo. Uno sconto piccolo, perche' parla di partite
# che devono ancora essere perse: un 1 costa un quinto della stagione.
SCONTO_INTEGRITA = {5: 1.0, 4: 0.97, 3: 0.93, 2: 0.87, 1: 0.80}

# Il bot ricava da solo due voti simili, e deve saperlo fare anche senza
# nessun file: la titolarita' e' la presenza attesa riportata su cinque
# gradini, la continuita' e' quante partite uno consegna rispetto a quante ne
# consegnerebbe uno del suo livello.
#
# QUELLI RICAVATI SI MOSTRANO E BASTA, e non correggono niente: sarebbero un
# giro a vuoto. La presenza attesa E' gia' la titolarita', e le assenze per
# infortunio degli anni scorsi stanno gia' dentro le presenze storiche —
# scontarle una seconda volta le conterebbe due volte. Il voto di un listino
# esterno invece corregge, perche' guarda avanti e non indietro.
SOGLIE_CONTINUITA = ((0.97, 5), (0.88, 4), (0.78, 3), (0.62, 2))

# --- Le etichette a parole dell'export ------------------------------------
#
# Sono sedici e si mostrano tutte, ma UNA SOLA entra nei conti, ed e' una
# scelta non una dimenticanza. Le altre quindici dicono cose che i numeri
# contengono gia' — "tanti gol", "cartellini", "subentrante" sono nelle
# statistiche e nei minuti — oppure parlano di varianza ("costante",
# "incostante"), che il motore non stima.
#
# RIGORISTA no. Chi tira i rigori quest'anno non sta in nessuna statistica
# dell'anno scorso, perche' spesso e' cambiato: il rigorista precedente e'
# stato venduto, o l'allenatore ha deciso diversamente in ritiro. E vale
# molto: quattro o cinque rigori a stagione, l'ottanta per cento segnati,
# tre punti l'uno su una trentina di partite.
RIGORISTA = "rigorista"
BONUS_RIGORISTA = 0.35

# Quanto vale, in punti a giornata, alzare di un voto la media di un singolo
# elemento della difesa. Il modificatore si calcola sulla media di portiere e
# tre difensori, quindi ognuno pesa un quarto; nella fascia dove si gioca la
# partita (media fra 6 e 7) il bonus passa da +1 a +4, cioe' circa tre punti
# per punto di media. Tre quarti di quei tre punti fanno il numero qui sotto.
PESO_MODIFICATORE = 0.75


@dataclass(frozen=True)
class ParametriLega:
    """Le regole della tua lega. Cambiano tutti i numeri, quindi si chiedono."""

    crediti: int = 500
    n_squadre: int = 8
    slot: dict[str, int] = field(
        default_factory=lambda: {"p": 3, "d": 8, "c": 8, "a": 6}
    )
    # Il modificatore di difesa premia la MEDIA VOTO di portiere e difensori,
    # non la fantamedia: con questa regola accesa il difensore che segna vale
    # meno di quello che non prende gol, e mezza asta cambia.
    modificatore_difesa: bool = False
    # Asta a buste chiuse: si offre una volta sola, al buio. Non esiste il
    # rilancio, quindi non esiste "il secondo piu' uno": chi offre poco per
    # risparmiare non perde crediti, perde il giocatore.
    offerte_segrete: bool = False

    @property
    def slot_per_squadra(self) -> int:
        return sum(self.slot.values())

    @property
    def slot_totali(self) -> int:
        """Quanti giocatori spariranno dal listone quando l'asta finisce."""
        return self.slot_per_squadra * self.n_squadre

    @property
    def budget_totale(self) -> int:
        return self.crediti * self.n_squadre

    def slot_ruolo_lega(self, ruolo: str) -> int:
        return self.slot[ruolo] * self.n_squadre


@dataclass(frozen=True)
class StagioneStat:
    stagione: str
    presenze: int
    fantamedia: float
    # Su quante giornate poggia la riga. 38 per una stagione conclusa, meno
    # per quella in corso: senza, tre presenze a settembre sarebbero
    # indistinguibili da tre presenze in un anno passato in infermeria.
    # Il resto solo per nome: quando "squadra" e' entrata in mezzo ai campi,
    # i chiamanti posizionali hanno silenziosamente messo la media voto nel
    # posto sbagliato, e nessun tipo se ne e' accorto.
    _: KW_ONLY
    giornate: int = 38
    squadra: str = ""
    media_voto: float = 0.0
    gol: int = 0
    assist: int = 0
    rigori_calciati: int = 0
    ammonizioni: int = 0
    espulsioni: int = 0

    @property
    def completa(self) -> bool:
        """Falso per la stagione in corso, che e' ancora a meta' strada."""
        return self.giornate >= 38


@dataclass(frozen=True)
class Attesa:
    """Cosa ci si aspetta da un giocatore nella stagione che comincia."""

    presenze: float
    fantamedia: float
    media_voto: float
    affidabilita: float
    # Quante partite ne giocherebbe uno del suo livello di mercato. Serve solo
    # come metro per l'integrita': da sola non vuol dire niente.
    presenze_del_suo_livello: float = 0.0
    presenze_storiche: float = 0.0


@dataclass(frozen=True)
class InCampo:
    """Quanto un giocatore sta davvero giocando, nella stagione in corso.

    Non e' storico e non e' listone: e' l'unica cosa che dice se il rendimento
    stimato avra' occasione di succedere. Vive qui e non in `StagioneStat`
    perche' non e' una stagione conclusa da pesare — e' lo stato di oggi.
    """

    minuti: int
    presenze: int
    giornate: int
    previsto_titolare: bool | None = None

    @property
    def quota_minuti(self) -> float:
        disponibili = 90.0 * self.giornate
        return min(1.0, self.minuti / disponibili) if disponibili > 0 else 0.0


@dataclass(frozen=True)
class Giudizi:
    """I voti da 1 a 5 di un listino esterno, quando c'e'.

    L'affidabilita' non entra in nessun conto: dice quanto un giocatore e'
    costante, che e' una cosa sulla varianza e non sulla media, e il motore
    stima medie. Si mostra e basta — inventarle un meccanismo vorrebbe dire
    aggiungere un numero che nessuno sa spiegare.
    """

    titolarita: int | None = None
    integrita: int | None = None
    affidabilita: int | None = None
    note: tuple[str, ...] = ()
    # La fascia come la chiama il listino esterno: 1 Top, 2 Semi-Top, 3 Terza,
    # 4 Quarta, 5 Outsider. Non e' la stessa cosa della fascia che il motore
    # calcola da solo — quella e' il quartile per FVM dentro il ruolo, questa
    # e' come le chiama chi ha scritto la strategia, ed e' quella che serve
    # quando la regola di composizione della rosa e' detta con quelle parole.
    fascia: int | None = None

    @property
    def rigorista(self) -> bool:
        return RIGORISTA in self.note


@dataclass(frozen=True)
class Fermo:
    """Un infortunio in corso: quanto dura, e la frase che lo dice.

    Il testo viaggia insieme al numero e non e' decorazione: «ipotizziamo un
    lungo stop» non e' una data, e chi offre deve poter leggere la frase invece
    della sua approssimazione.
    """

    giornate_fuori: int
    testo: str = ""
    datato: bool = False


@dataclass(frozen=True)
class Giocatore:
    id_fc: int
    nome: str
    squadra: str
    ruolo: str
    quota: int
    fvm: int
    storico: tuple[StagioneStat, ...] = ()
    campo: InCampo | None = None
    fermo: Fermo | None = None
    giudizi: Giudizi | None = None
    # Vero se sta in TUTTE E DUE le liste: il listone e il file delle fasce.
    # Il listone di fantacalcio.it si porta dietro chi e' andato via a mercato
    # aperto — Leao risultava ancora al Milan con il suo FVM da 75 — e un
    # giocatore che non esiste piu' non e' solo un nome sbagliato da
    # consigliare: entra fra i comprabili, si prende la sua fetta dei crediti
    # della lega e sposta il prezzo di tutti gli altri. Il file delle fasce e'
    # piu' recente e lo sa, quindi vale come smentita.
    in_lista: bool = True
    # Le squalifiche NON entrano nel valore d'asta: una giornata su trentotto
    # e' rumore, e scontarla vorrebbe dire pagare meno un giocatore per una
    # cosa che sara' finita prima che tu lo schieri. Cambiano la formazione di
    # domenica, e quello e' l'unico posto dove si leggono.
    squalificato: int = 0
    diffidato: bool = False


@dataclass(frozen=True)
class Valutazione:
    giocatore: Giocatore
    presenze_attese: float
    fantamedia_attesa: float
    media_voto_attesa: float
    punti_attesi: float
    vorp: float
    valore: float  # crediti che vale per te
    prezzo_mercato: float  # crediti che costera'
    fascia: int  # 1 = top del ruolo, 5 = fuori dai comprabili
    rango_ruolo: int
    # I due voti da 1 a 5 che il bot ricava da solo, senza nessun file.
    # Zero sulla continuita' vuol dire "non abbastanza storia per dirlo".
    titolarita: int = 0
    continuita: int = 0
    # Quanto la stima poggia su partite giocate davvero invece che sul solo
    # consenso di mercato: 1 = due stagioni piene alle spalle, 0 = mai visto
    # in Serie A. Non e' un difetto, e' un rischio - e va detto a chi offre.
    affidabilita: float = 1.0

    @property
    def scommessa(self) -> bool:
        """Vero quando il numero e' un'ipotesi, non una misura."""
        return self.affidabilita < 0.5

    @property
    def scarto(self) -> float:
        """Positivo = occasione, negativo = trappola del listone."""
        return self.valore - self.prezzo_mercato

    @property
    def affare(self) -> float:
        """Lo scarto in rapporto al prezzo: +0.30 = vale il 30% in piu'."""
        return self.scarto / max(self.prezzo_mercato, 1.0)


def _regressione_pesata(
    punti: list[tuple[float, float, float]],
) -> tuple[float, float]:
    """Minimi quadrati pesati su (x, y, peso): restituisce (intercetta, pendenza).

    Con meno di tre punti utili non c'e' niente da stimare e si risponde con
    la media pesata e pendenza zero: il chiamante ottiene comunque un numero
    sensato invece di una divisione per zero.
    """
    peso_tot = sum(p for _, _, p in punti)
    if peso_tot <= 0 or len(punti) < 3:
        media = sum(y * p for _, y, p in punti) / peso_tot if peso_tot else 0.0
        return media, 0.0
    mx = sum(x * p for x, _, p in punti) / peso_tot
    my = sum(y * p for _, y, p in punti) / peso_tot
    sxx = sum(p * (x - mx) ** 2 for x, _, p in punti)
    sxy = sum(p * (x - mx) * (y - my) for x, y, p in punti)
    if sxx <= 1e-9:
        return my, 0.0
    pendenza = sxy / sxx
    return my - pendenza * mx, pendenza


def _x_fvm(fvm: int) -> float:
    """Il FVM entra in scala logaritmica: da 10 a 20 e' un salto, da 400 a 410 no."""
    return math.log10(max(fvm, 1) + 1)


def forza_club(giocatori: list[Giocatore]) -> dict[str, float]:
    """Quanto vale la rosa di ogni squadra di Serie A, secondo il mercato.

    E' la somma dei FVM dei suoi giocatori: non misura la classifica, misura
    quanto il fantacalcio si aspetta da chi ci gioca dentro, che e' esattamente
    la cosa che serve.
    """
    forze: dict[str, float] = {}
    quanti: dict[str, int] = {}
    for g in giocatori:
        if g.squadra:
            forze[g.squadra] = forze.get(g.squadra, 0.0) + max(g.fvm, 1)
            quanti[g.squadra] = quanti.get(g.squadra, 0) + 1
    # Le sigle con due nomi dentro non sono squadre: tenerle voleva dire
    # avere una "squadra piu' debole" con forza 1, e chi arrivava da un club
    # fuori listone si ritrovava con due punti di fantamedia regalati.
    return {
        club: forza
        for club, forza in forze.items()
        if quanti[club] >= ROSA_MINIMA_PER_CONTARE
    }


def _entro_il_tetto(spostamento: float) -> float:
    """Nessuna correzione di contesto vale piu' di mezzo voto."""
    return min(max(spostamento, -MASSIMO_SPOSTAMENTO_CLUB), MASSIMO_SPOSTAMENTO_CLUB)


def _x_club(club: str, forze: dict[str, float]) -> float:
    """La forza del club in scala logaritmica.

    Un club che non e' nel listone e' una squadra retrocessa o straniera: vale
    quanto la piu' debole della Serie A, che e' il modo meno sbagliato di dire
    "veniva da un posto peggiore di questo".
    """
    if not forze:
        return 0.0
    valore = forze.get(club) or min(forze.values())
    return math.log10(max(valore, 1.0))


def _coefficiente_club(
    elenco: list[Giocatore], forze: dict[str, float], quale: int = 1
) -> float:
    """Di quanto cambia la fantamedia passando a un club piu' forte.

    Stimato, non deciso a tavolino. Il problema e' che la qualita' del club e
    quella del giocatore vanno insieme - i campioni giocano nelle squadre
    forti - quindi una regressione diretta attribuirebbe al club merito che e'
    del giocatore. Si toglie prima l'effetto del FVM da entrambe le variabili
    e si guarda cosa resta: e' la parte di rendimento che dipende davvero da
    dove giochi.

    Serve a un caso solo ma frequente: chi ha cambiato maglia in estate ha uno
    storico costruito altrove, e senza questa correzione un difensore arrivato
    dal fondo classifica in una squadra da primi posti viene valutato con i
    voti che prendeva prima.
    """
    campione = []
    for g in elenco:
        grezzo = _storico_grezzo(g)
        voto, presenze_pesate = grezzo[quale], grezzo[3]
        if presenze_pesate < PRESENZE_PER_REGRESSIONE or voto <= 0:
            continue
        # Solo chi e' rimasto dov'era: per gli altri il club dello storico non
        # e' quello di adesso, ed e' proprio la confusione da evitare.
        if any(s.squadra and s.squadra != g.squadra for s in g.storico[:1]):
            continue
        campione.append(
            (_x_fvm(g.fvm), _x_club(g.squadra, forze), voto, presenze_pesate)
        )
    if len(campione) < 10:
        return 0.0
    _, b_fm = _regressione_pesata([(x, y, w) for x, _, y, w in campione])
    a_fm = _media_pesata([(y, w) for _, _, y, w in campione]) - b_fm * _media_pesata(
        [(x, w) for x, _, _, w in campione]
    )
    _, b_club = _regressione_pesata([(x, c, w) for x, c, _, w in campione])
    a_club = _media_pesata([(c, w) for _, c, _, w in campione]) - b_club * _media_pesata(
        [(x, w) for x, _, _, w in campione]
    )
    residui = [
        (c - (a_club + b_club * x), y - (a_fm + b_fm * x), w)
        for x, c, y, w in campione
    ]
    _, coefficiente = _regressione_pesata(residui)
    # Un tetto: oltre mezzo voto di scarto fra il club piu' forte e il piu'
    # debole non ci si crede, e una stima rumorosa non deve poter ribaltare
    # la valutazione di un giocatore.
    return min(max(coefficiente, -MASSIMO_EFFETTO_CLUB), MASSIMO_EFFETTO_CLUB)


def _media_pesata(valori: list[tuple[float, float]]) -> float:
    peso = sum(w for _, w in valori)
    return sum(v * w for v, w in valori) / peso if peso else 0.0


def _storico_grezzo(g: Giocatore) -> tuple[float, float, float, float]:
    """Lo storico com'e', senza correzioni: serve a stimare le correzioni."""
    return _storico_pesato(g)


def _storico_pesato(
    g: Giocatore,
    forze: dict[str, float] | None = None,
    coefficienti: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float, float, float]:
    """(presenze medie, fantamedia, media voto, presenze pesate totali).

    Se si passano le forze dei club, i voti di ogni stagione vengono riportati
    al club di adesso: quello che avrebbe fatto giocando dove gioca oggi, non
    dove giocava allora. Fantamedia e media voto hanno correzioni diverse -
    cambiare squadra sposta i gol e i voti in misura diversa.
    """
    coeff_fm, coeff_mv = coefficienti
    peso_stagioni = 0.0
    somma_presenze = 0.0
    somma_fm = 0.0
    somma_mv = 0.0
    peso_voti = 0.0
    for i, s in enumerate(g.storico[: len(PESI_STAGIONE)]):
        w = PESI_STAGIONE[i]
        fantamedia, media_voto = s.fantamedia, s.media_voto
        if forze and s.squadra and s.squadra != g.squadra:
            salto = _x_club(g.squadra, forze) - _x_club(s.squadra, forze)
            fantamedia += _entro_il_tetto(coeff_fm * salto)
            if media_voto:
                media_voto += _entro_il_tetto(coeff_mv * salto)
        # LA STAGIONE IN CORSO NON ENTRA NELLE PRESENZE, e non e' una svista.
        # Quanto uno giochera' lo dice gia' `campo`, che dei minuti sa anche
        # quanti sono e li sconta per quante giornate si sono giocate. Farlo
        # dire due volte alla stessa evidenza — tre presenze su tre — vorrebbe
        # dire che tre giornate parlano con due voci. Sui VOTI invece entra
        # eccome: li' `campo` non sa niente, ed e' l'unico posto dove si vede
        # cosa sta rendendo chi in Serie A non c'era mai stato.
        if s.completa:
            peso_stagioni += w
            somma_presenze += w * s.presenze
        # I voti si pesano per presenze: 10 preso in una partita non e' una
        # stagione da 10.
        somma_fm += w * s.presenze * fantamedia
        somma_mv += w * s.presenze * media_voto
        peso_voti += w * s.presenze
    presenze_medie = somma_presenze / peso_stagioni if peso_stagioni else 0.0
    fantamedia = somma_fm / peso_voti if peso_voti else 0.0
    media_voto = somma_mv / peso_voti if peso_voti else 0.0
    return presenze_medie, fantamedia, media_voto, peso_voti


def pesi_prezzo(
    comprabili: list[Giocatore], osservati: dict[int, float] | None = None
) -> dict[int, float]:
    """Quanto pesera' ogni giocatore sul budget speso dalla lega.

    Se arrivano i **prezzi osservati** - quanto e' stato pagato davvero nelle
    aste vere, importati da un tool esterno - quelli vincono sulla stima per
    chi ce li ha: un dato raccolto su migliaia di aste sa quello che nessuna
    formula puo' dedurre dal listone. Chi non ce li ha resta sulla stima, e le
    due scale vengono riportate l'una sull'altra prima di mescolarle,
    altrimenti meta' listone varrebbe dieci volte l'altra meta'.

    Due segnali dicono la stessa cosa in scale diverse: la **quotazione**, che
    e' in crediti su base 500 ma e' solo la base d'asta, e il **FVM**, che
    stima il prezzo reale ma su una scala tutta sua e con una coda lunghissima
    (il primo attaccante arriva a valere il triplo del secondo, cosa che in
    un'asta vera non succede mai).

    Si usa la loro media geometrica sulle quote normalizzate: tiene
    l'ordinamento del FVM, che e' il segnale piu' informato, e ne comprime la
    coda riportandola vicino alla quotazione. Senza questa compressione il bot
    consigliava di spendere un terzo del budget su un solo attaccante.
    """
    somma_quote = sum(max(g.quota, 1) for g in comprabili) or 1
    somma_fvm = sum(max(g.fvm, 1) for g in comprabili) or 1
    stimati = {
        g.id_fc: math.sqrt(
            (max(g.quota, 1) / somma_quote) * (max(g.fvm, 1) / somma_fvm)
        )
        for g in comprabili
    }
    if not osservati:
        return stimati

    noti = {
        g.id_fc: osservati[g.id_fc]
        for g in comprabili
        if osservati.get(g.id_fc, 0) > 0
    }
    if len(noti) < max(10, len(comprabili) // 10):
        # Troppi pochi dati per fidarsi: meglio una stima coerente che una
        # mescolanza di due scale diverse.
        return stimati

    # I prezzi osservati arrivano nella loro scala (di solito base 500). Si
    # portano sulla stessa scala delle stime confrontando i due totali sui
    # giocatori che stanno in entrambe le liste.
    totale_stimato = sum(stimati[i] for i in noti)
    totale_osservato = sum(noti.values())
    fattore = totale_stimato / totale_osservato if totale_osservato > 0 else 1.0
    return {
        g.id_fc: noti[g.id_fc] * fattore if g.id_fc in noti else stimati[g.id_fc]
        for g in comprabili
    }


def _fascia(posizione: int, comprabili_nel_ruolo: int) -> int:
    """1..4 dentro i comprabili del ruolo, 5 per chi resta fuori."""
    if comprabili_nel_ruolo <= 0 or posizione >= comprabili_nel_ruolo:
        return 5
    quarto = max(1, comprabili_nel_ruolo // 4)
    return min(4, posizione // quarto + 1)


def titolarita_stimata(presenze: float) -> int:
    """La presenza attesa su cinque gradini, per dirla come la dice un listino."""
    for voto in (5, 4, 3, 2):
        soglia = (PRESENZE_DA_TITOLARITA[voto] + PRESENZE_DA_TITOLARITA[voto - 1]) / 2
        if presenze >= soglia:
            return voto
    return 1


def continuita_stimata(
    storico: tuple[StagioneStat, ...], del_suo_livello: float
) -> int:
    """Quante partite consegna davvero, rispetto a uno del suo livello.

    SI CHIAMA CONTINUITA' E NON INTEGRITA', e la differenza non e' una
    sfumatura: **le presenze non sanno dire perche'** uno ha giocato poco.
    Provato su dati veri, ogni regola sbagliava qualcuno —

      · la media puniva Malen, che ha diciotto presenze perche' e' arrivato a
        gennaio, non perche' si rompe;
      · il massimo assolveva Bremer, che una delle due stagioni l'ha passata
        con il crociato rotto, e Zaniolo, che di mestiere si fa male.

    Non c'e' una terza formula che le separi: la causa non e' nel dato. Quello
    che invece si misura senza ambiguita' e' quante domeniche quel giocatore
    ti consegna — infortuni, panchina e mercato messi insieme — ed e' anche
    quello che serve per decidere. L'integrita' vera, che guarda avanti invece
    che indietro, resta quella del listino esterno, e si mostra accanto.

    Servono due stagioni concluse: con una sola non c'e' continuita' da
    misurare, e zero vuol dire "non lo so".
    """
    complete = [s for s in storico if s.completa and s.presenze > 0]
    if del_suo_livello <= 0 or len(complete) < 2:
        return 0
    media = sum(s.presenze for s in complete) / len(complete)
    quota = media / del_suo_livello
    for soglia, voto in SOGLIE_CONTINUITA:
        if quota >= soglia:
            return voto
    return 1


def _col_giudizio(presenze_attese: float, giudizi: Giudizi | None) -> float:
    """Il prior corretto con quello che dice chi il campionato lo guarda.

    Sta PRIMA della correzione sui minuti e non dopo, ed e' l'ordine giusto:
    questo resta un prior — informato, ma pur sempre un'opinione di agosto — e
    quello che succede in campo deve poterlo smentire come smentisce il FVM.
    """
    if giudizi is None:
        return presenze_attese
    if giudizi.titolarita in PRESENZE_DA_TITOLARITA:
        presenze_attese = (
            PESO_TITOLARITA * PRESENZE_DA_TITOLARITA[giudizi.titolarita]
            + (1 - PESO_TITOLARITA) * presenze_attese
        )
    if giudizi.integrita in SCONTO_INTEGRITA:
        presenze_attese *= SCONTO_INTEGRITA[giudizi.integrita]
    return presenze_attese


def disponibilita_osservata(campo: InCampo) -> float:
    """La quota di partite che sta giocando davvero, da 0 a 1.

    DUE MISURE, E SI PRENDE LA PIU' SEVERA, perche' sbagliano in due direzioni
    opposte e nessuna delle due basta da sola:

      · le **presenze** dicono in quante partite e' entrato, e contano uguale
        chi gioca novanta minuti e chi ne gioca cinque. Lucca ha giocato tutte
        e tre le partite del Napoli e quaranta minuti in totale: sulle sole
        presenze risulterebbe titolare fisso;
      · i **minuti** dicono quanto ha giocato, e puniscono chi ha saltato una
        partita per squalifica pur essendo il titolare indiscusso.

    Il minimo fra le due tiene il difetto di nessuna: chi gioca sempre e per
    intero arriva esattamente a 1, il subentrante fisso scende dove merita, e
    lo squalificato di una giornata perde una giornata e non la stagione.
    """
    if campo.giornate <= 0:
        return 0.0
    da_presenze = campo.presenze / campo.giornate
    da_minuti = campo.minuti / (campo.giornate * MINUTI_DA_TITOLARE)
    osservata = min(1.0, da_presenze, da_minuti)
    if campo.previsto_titolare:
        osservata = max(osservata, QUOTA_DA_PREVISTO)
    return osservata


def _presenze_col_campo(
    presenze_attese: float,
    campo: InCampo | None,
    ruolo: str = "c",
    fermo: Fermo | None = None,
) -> float:
    """Corregge le presenze attese con quello che le giornate hanno mostrato.

    La correzione non e' una sostituzione: e' una media pesata fra quello che
    si credeva ad agosto e quello che si e' visto da allora, e il peso di
    quello che si e' visto cresce con le giornate. A tre giornate un portiere
    con zero minuti non vale zero — vale molto meno di prima, che e' quanto il
    campione permette di dire.

    Chi non ha nessuna riga qui non viene toccato: nessun dato non e' un dato
    cattivo, ed e' la differenza fra un giocatore che non gioca e un giocatore
    di cui non sappiamo niente.
    """
    base = presenze_attese
    if campo is not None and campo.giornate > 0:
        meta = GIORNATE_PER_CREDERCI.get(ruolo, 3.0)
        peso = campo.giornate / (campo.giornate + meta)
        osservata = disponibilita_osservata(campo)
        atteso = presenze_attese / 38.0
        # QUANDO SAPPIAMO PERCHE' NON GIOCA, la sua assenza smette di essere
        # una notizia. Buongiorno non ha giocato un minuto ed e' il centrale
        # titolare del Napoli: leggere quello zero come una gerarchia vorrebbe
        # dire scambiare un infortunio per una bocciatura, e scartare il
        # giocatore proprio nel momento in cui costa meno.
        #
        # SOLO VERSO IL BASSO, pero'. L'infortunio spiega le partite saltate,
        # non quelle giocate: a chi e' sceso in campo piu' di quanto ci si
        # aspettasse i minuti si contano per intero, altrimenti una nota di
        # "in dubbio per domenica" cancellerebbe una buona notizia vera.
        if fermo is not None and fermo.giornate_fuori > 0 and osservata < atteso:
            peso *= PESO_CAMPO_SE_FERMO
        base = 38.0 * (peso * osservata + (1 - peso) * atteso)

    if fermo is not None and fermo.giornate_fuori > 0:
        # E poi le giornate che salta si tolgono, ma solo da quelle che
        # restano: a settembre sono quasi tutte, a marzo quasi nessuna, e lo
        # stesso infortunio vale due cose diverse.
        giocate = campo.giornate if campo is not None else 0
        rimaste = max(1.0, 38.0 - giocate)
        base *= max(0.0, rimaste - fermo.giornate_fuori) / rimaste
    return base


def _attese_per_ruolo(
    elenco: list[Giocatore],
    forze: dict[str, float] | None = None,
) -> dict[int, Attesa]:
    """Presenze, fantamedia e media voto attese per ogni giocatore di un ruolo.

    Chi ha uno storico solido parla da solo; chi non ce l'ha (uno straniero
    appena arrivato, un ventenne di ritorno dal prestito) viene descritto dal
    mercato, attraverso la relazione FVM -> rendimento stimata sugli altri.

    La media voto percorre tutta la strada della fantamedia perche' serve al
    modificatore di difesa, dove contano i voti e non i bonus.
    """
    forze = forze or {}
    coefficienti = (
        (
            _coefficiente_club(elenco, forze, quale=1),
            _coefficiente_club(elenco, forze, quale=2),
        )
        if forze
        else (0.0, 0.0)
    )
    campione_fm: list[tuple[float, float, float]] = []
    campione_mv: list[tuple[float, float, float]] = []
    campione_presenze: list[tuple[float, float, float]] = []
    for g in elenco:
        presenze_medie, fantamedia, media_voto, presenze_pesate = _storico_pesato(
            g, forze, coefficienti
        )
        if presenze_pesate >= PRESENZE_PER_REGRESSIONE and fantamedia > 0:
            x = _x_fvm(g.fvm)
            campione_fm.append((x, fantamedia, presenze_pesate))
            campione_presenze.append((x, presenze_medie, presenze_pesate))
            if media_voto > 0:
                campione_mv.append((x, media_voto, presenze_pesate))
    a_fm, b_fm = _regressione_pesata(campione_fm)
    a_mv, b_mv = _regressione_pesata(campione_mv)
    a_pres, b_pres = _regressione_pesata(campione_presenze)

    attese: dict[int, Attesa] = {}
    for g in elenco:
        presenze_medie, fantamedia, media_voto, presenze_pesate = _storico_pesato(
            g, forze, coefficienti
        )
        x = _x_fvm(g.fvm)
        presenze_da_mercato = min(max(a_pres + b_pres * x, 2.0), 37.0)
        fiducia = min(1.0, presenze_pesate / PRESENZE_PER_FIDARSI)
        presenze_attese = (
            fiducia * presenze_medie + (1 - fiducia) * presenze_da_mercato
        )
        presenze_attese = _col_giudizio(presenze_attese, g.giudizi)
        presenze_attese = _presenze_col_campo(
            presenze_attese, g.campo, g.ruolo, g.fermo
        )
        attese[g.id_fc] = Attesa(
            presenze_del_suo_livello=presenze_da_mercato,
            presenze_storiche=presenze_medie,
            presenze=min(max(presenze_attese, 0.0), 38.0),
            fantamedia=max(
                fiducia * fantamedia
                + (1 - fiducia) * (a_fm + b_fm * x)
                + (
                    BONUS_RIGORISTA
                    if g.giudizi is not None and g.giudizi.rigorista
                    else 0.0
                ),
                0.0,
            ),
            media_voto=max(
                fiducia * media_voto + (1 - fiducia) * (a_mv + b_mv * x), 0.0
            ),
            affidabilita=fiducia,
        )
    return attese


def valuta(
    giocatori: list[Giocatore],
    parametri: ParametriLega | None = None,
    prezzi_osservati: dict[int, float] | None = None,
) -> dict[int, Valutazione]:
    """Valuta l'intero listone in un colpo solo.

    Un giocatore non si puo' valutare da solo: il suo prezzo dipende da quanti
    crediti ci sono nella lega e da chi altro c'e' nel suo ruolo. Per questo la
    funzione prende la lista intera e restituisce una mappa per id.
    """
    parametri = parametri or ParametriLega()
    per_ruolo: dict[str, list[Giocatore]] = {r: [] for r in RUOLI}
    for g in giocatori:
        if g.ruolo in per_ruolo:
            per_ruolo[g.ruolo].append(g)

    # DUE POPOLAZIONI, NON UNA. Tutti servono a stimare: la regressione sul
    # FVM e l'effetto club sono piu' precisi con piu' storie dentro, e chi ha
    # cambiato campionato la sua storia in Serie A ce l'ha ancora. Ma il
    # MERCATO e' fatto solo da chi si puo' ancora comprare: chi e' andato via
    # non consuma crediti, non occupa uno slot e non e' il rimpiazzo di
    # nessuno. Tenerlo dentro spostava il prezzo di tutti gli altri.
    di_mercato = {
        ruolo: [g for g in elenco if g.in_lista] or elenco
        for ruolo, elenco in per_ruolo.items()
    }

    forze = forza_club(giocatori)
    attese: dict[int, Attesa] = {}
    for elenco in per_ruolo.values():
        attese.update(_attese_per_ruolo(elenco, forze))
    punti = {id_fc: a.presenze * a.fantamedia for id_fc, a in attese.items()}

    # Chi verra' comprato lo decide il mercato, non il nostro modello: sono i
    # primi per FVM di ogni ruolo, tanti quanti gli slot che la lega deve
    # riempire. Sono loro, e solo loro, a consumare i crediti dell'asta.
    comprabili: list[Giocatore] = []
    fasce: dict[int, int] = {}
    for ruolo, elenco in di_mercato.items():
        per_mercato = sorted(elenco, key=lambda g: (-g.fvm, -g.quota))
        quanti = min(len(per_mercato), parametri.slot_ruolo_lega(ruolo))
        for posizione, g in enumerate(per_mercato):
            fasce[g.id_fc] = _fascia(posizione, quanti)
        comprabili.extend(per_mercato[:quanti])

    # Il guadagno vero di un titolare non e' quanto segna: e' quanto segna in
    # piu' del giocatore che schiereresti al suo posto, moltiplicato per le
    # domeniche in cui c'e'. Un trequartista da 7.3 che gioca 24 partite vale
    # piu' di un mediano da 6.2 che le gioca tutte, e la somma dei punti
    # stagionali diceva il contrario: quella e' la formula di un gioco senza
    # panchina, e il fantacalcio la panchina ce l'ha.
    vorp: dict[int, float] = {}
    for ruolo, elenco in per_ruolo.items():
        if not elenco:
            continue
        base = _fantamedia_di_rimpiazzo(
            di_mercato[ruolo], punti, attese, parametri, ruolo
        )
        # Con il modificatore acceso un difensore rende due volte: con la sua
        # fantamedia, e alzando la media voto del reparto. Il secondo canale
        # premia chi non prende gol, non chi li segna.
        base_voto = (
            _voto_di_rimpiazzo(
                di_mercato[ruolo], punti, attese, parametri, ruolo
            )
            if parametri.modificatore_difesa and ruolo in RUOLI_DELLA_DIFESA
            else 0.0
        )
        for g in elenco:
            a = attese[g.id_fc]
            guadagno = a.fantamedia - base
            if base_voto:
                guadagno += PESO_MODIFICATORE * (a.media_voto - base_voto)
            vorp[g.id_fc] = max(0.0, a.presenze * guadagno)

    # Dai punti ai crediti. Ogni giocatore comprato costa almeno 1 e il resto
    # del budget si spartisce in proporzione: al FVM compresso per il prezzo,
    # al VORP per il valore. La somma dei prezzi torna esattamente il budget
    # della lega - se compri al listino finisci con la rosa piena e zero
    # crediti, che e' la definizione di prezzo giusto.
    liberi = max(0.0, parametri.budget_totale - len(comprabili))
    totale_vorp = sum(vorp[g.id_fc] for g in comprabili)
    pesi = pesi_prezzo(comprabili, prezzi_osservati)
    totale_peso = sum(pesi.values())
    ranghi = _ranghi_per_valore(di_mercato, vorp)

    valutazioni: dict[int, Valutazione] = {}
    for g in giocatori:
        if g.id_fc not in vorp:
            continue
        a = attese[g.id_fc]
        # Il valore si calcola per tutti, anche per chi il mercato ignora:
        # un giocatore fuori dai comprabili con VORP alto e' l'occasione che
        # ti fa vincere l'asta a due crediti, e deve poter emergere.
        valore = 1.0 + (
            liberi * vorp[g.id_fc] / totale_vorp if totale_vorp > 0 else 0.0
        )
        peso = pesi.get(g.id_fc)
        prezzo = 1.0 + (
            liberi * peso / totale_peso if peso is not None and totale_peso > 0 else 0.0
        )
        valutazioni[g.id_fc] = Valutazione(
            giocatore=g,
            presenze_attese=a.presenze,
            fantamedia_attesa=a.fantamedia,
            media_voto_attesa=a.media_voto,
            punti_attesi=punti[g.id_fc],
            vorp=vorp[g.id_fc],
            valore=valore,
            prezzo_mercato=prezzo,
            fascia=fasce.get(g.id_fc, 5),
            rango_ruolo=ranghi.get(g.id_fc, 0),
            titolarita=titolarita_stimata(a.presenze),
            continuita=continuita_stimata(
                g.storico, a.presenze_del_suo_livello
            ),
            affidabilita=a.affidabilita,
        )
    return valutazioni


def _fantamedia_di_rimpiazzo(
    elenco: list[Giocatore],
    punti: dict[int, float],
    attese: dict[int, Attesa],
    parametri: ParametriLega,
    ruolo: str,
) -> float:
    """La fantamedia che ottieni gratis in quel ruolo.

    E' la media di chi viene comprato nell'ultimo quarto del ruolo: i
    giocatori che a fine asta vanno via a uno o due crediti e che finiranno
    comunque in panchina a te come a tutti gli altri.
    """
    ordinati = sorted(elenco, key=lambda g: punti[g.id_fc], reverse=True)
    fine = min(len(ordinati), parametri.slot_ruolo_lega(ruolo))
    inizio = max(1, int(fine * 0.75))
    coda = ordinati[inizio:fine] or ordinati[-1:]
    return sum(attese[g.id_fc].fantamedia for g in coda) / len(coda)


def _voto_di_rimpiazzo(
    elenco: list[Giocatore],
    punti: dict[int, float],
    attese: dict[int, Attesa],
    parametri: ParametriLega,
    ruolo: str,
) -> float:
    """La media voto che ottieni gratis in quel ruolo, per il modificatore."""
    ordinati = sorted(elenco, key=lambda g: punti[g.id_fc], reverse=True)
    fine = min(len(ordinati), parametri.slot_ruolo_lega(ruolo))
    inizio = max(1, int(fine * 0.75))
    coda = ordinati[inizio:fine] or ordinati[-1:]
    return sum(attese[g.id_fc].media_voto for g in coda) / len(coda)


def _ranghi_per_valore(
    per_ruolo: dict[str, list[Giocatore]], vorp: dict[int, float]
) -> dict[int, int]:
    """Posizione di ogni giocatore nel suo ruolo secondo quanto vale per te."""
    ranghi: dict[int, int] = {}
    for elenco in per_ruolo.values():
        for posizione, g in enumerate(
            sorted(elenco, key=lambda g: -vorp[g.id_fc])
        ):
            ranghi[g.id_fc] = posizione + 1
    return ranghi
