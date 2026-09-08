"""Come i numeri diventano messaggi.

Regola unica di questo modulo: durante l'asta hai cinque secondi e una mano
sola. La cifra che serve - fino a quanto posso offrire - sta sulla prima riga
utile, in grande, da sola. Tutto il resto e' contesto e puo' aspettare la
seconda occhiata.
"""

from __future__ import annotations

from ..motore.asta import Consiglio, Squadra, StatoAsta
from ..motore.valutazione import NOMI_RUOLO, RUOLI, Valutazione

SIMBOLO_RUOLO = {"p": "P", "d": "D", "c": "C", "a": "A"}
PLURALE_RUOLO = {
    "p": "Portieri",
    "d": "Difensori",
    "c": "Centrocampisti",
    "a": "Attaccanti",
}
GIUDIZI = {
    "prendilo": "PRENDILO",
    "vale il prezzo": "vale il prezzo",
    "solo se scende": "solo se scende",
    "lascialo": "LASCIALO",
}


def _fm(valore: float) -> str:
    return f"{valore:.2f}".replace(".", ",")


def in_corso(g):
    """La stagione che si sta giocando, se ne abbiamo letto qualche giornata."""
    return next((s for s in g.storico if not s.completa), None)


def _bonus_e_malus(s) -> str:
    """Cosa ha portato e cosa ha tolto, in parole."""
    bonus = []
    if s.gol:
        bonus.append(f"{s.gol} gol")
    if s.assist:
        bonus.append(f"{s.assist} assist")
    malus = []
    if s.ammonizioni:
        malus.append(f"{s.ammonizioni} amm")
    if s.espulsioni:
        malus.append(f"{s.espulsioni} esp")
    pezzi = ", ".join(bonus + malus)
    return pezzi or "nessun bonus"


def riga_infortunio(g) -> list[str]:
    """L'infortunio, e sempre con la frase originale sotto.

    Sta in cima alla scheda, sopra il rendimento e sopra lo storico, perche' e'
    il dato che cambia la decisione piu' di ogni altro: nessun rendimento
    succede mentre uno e' in infermeria. E il testo si mostra intero perche' la
    stima in giornate e' una lettura di una frase, non una diagnosi.
    """
    f = g.fermo
    if f is None:
        return []
    if f.giornate_fuori <= 0:
        titolo = "IN DUBBIO"
    elif f.giornate_fuori == 1:
        titolo = "FERMO: salta la prossima"
    else:
        forse = "" if f.datato else " circa"
        titolo = f"FERMO:{forse} {f.giornate_fuori} giornate"
    righe = [f"\n<b>⚕ {titolo}</b>"]
    if f.testo:
        righe.append(f"<i>{f.testo}</i>")
    return righe


def riga_giudizi(g) -> list[str]:
    """I tre voti da 1 a 5 del listino esterno, quando ci sono.

    Si mostrano come pallini pieni e vuoti perche' vanno letti di sfuggita, e
    con una frase sola quando uno dei tre e' basso: un titolarissimo con
    integrita' 1 e' una trappola che il numero da solo non racconta — Dybala e
    Zaniolo hanno entrambi titolarita' 5 e integrita' 1.
    """
    j = getattr(g, "giudizi", None)
    if j is None:
        return []
    voci = [
        ("titolarita", j.titolarita),
        ("integrita", j.integrita),
        ("affidabilita", j.affidabilita),
    ]
    pezzi = [
        f"{nome} {'●' * n}{'○' * (5 - n)}" for nome, n in voci if n is not None
    ]
    if not pezzi:
        return []
    righe = [f"<i>{' · '.join(pezzi)}</i>"]
    if j.titolarita is not None and j.titolarita >= 4 and (j.integrita or 5) <= 2:
        righe.append("<i>⚠ gioca sempre quando c'e', e spesso non c'e'.</i>")
    return righe


def riga_continuita(v) -> list[str]:
    """Quante domeniche consegna, misurate dal bot sulle stagioni concluse.

    Sta accanto ai voti del listino e non al loro posto: quello guarda avanti
    (si fara' male?), questo guarda indietro (quante ne ha date?), e a
    settembre non e' detto che dicano la stessa cosa.
    """
    if not v.continuita:
        return []
    parole = {
        5: "le gioca quasi tutte",
        4: "ne salta poche",
        3: "ne salta un pezzo",
        2: "te ne da' due terzi",
        1: "ne consegna meta'",
    }
    return [
        f"<i>continuita {'●' * v.continuita}{'○' * (5 - v.continuita)} — "
        f"{parole[v.continuita]}, contando anche panchina e mercato</i>"
    ]


def segno_campo(g) -> str:
    """Il marchio compatto per le liste: chi non gioca deve saltare all'occhio.

    Una lista di consigli e' quello che si legge di corsa mentre il banditore
    chiama, e un valore alto accanto a un nome che non scende in campo e' il
    modo piu' rapido di buttare crediti. Due caratteri bastano a fermare la
    mano.
    """
    if g.fermo is not None and g.fermo.giornate_fuori > 0:
        return "⚕"
    c = g.campo
    if c is None or c.giornate <= 0:
        return " "
    if c.previsto_titolare:
        return " "
    if c.presenze == 0:
        return "✕"
    return "·" if c.quota_minuti < 0.45 else " "


def stato_campo(g) -> list[str]:
    """Come sta giocando adesso: minuti, bonus di questa stagione, previsione.

    E' il blocco che risponde alla domanda che il listone non sa sentire —
    "ma questo gioca?" — e va letto prima del rendimento atteso, perche' un
    rendimento che non ha occasione di succedere non e' un rendimento.
    """
    c = g.campo
    s = in_corso(g)
    if c is None or c.giornate <= 0:
        return []
    righe = ["\n<b>Come sta adesso</b>"]
    minuti = f"{c.minuti}' su {90 * c.giornate}"
    if c.presenze:
        minuti += f" in {c.presenze} partite"
    righe.append(f"<code>{minuti}</code>")
    if s is not None and s.presenze:
        righe.append(f"<code>fm {_fm(s.fantamedia)}</code> · {_bonus_e_malus(s)}")
    if c.previsto_titolare is True:
        righe.append("<i>previsto titolare nella prossima</i>")
    elif c.previsto_titolare is False and c.quota_minuti < 0.60:
        righe.append("<i>⚠ non e' nell'undici previsto della prossima</i>")
    # Se sappiamo gia' perche' non gioca, ripeterlo come sospetto sarebbe
    # peggio che tacerlo: il blocco dell'infortunio l'ha appena spiegato, e
    # "non ha giocato un minuto" letto sotto suonerebbe come una seconda
    # colpa invece che come la stessa cosa.
    if g.fermo is not None:
        return righe
    if c.presenze == 0:
        righe.append("<b>⚠ non ha ancora giocato un minuto.</b>")
    elif c.quota_minuti < 0.45:
        righe.append("<i>⚠ finora e' una riserva: entra, non parte.</i>")
    return righe


def scheda(c: Consiglio, stato: StatoAsta) -> str:
    """La scheda che leggi mentre il banditore aspetta."""
    v = c.valutazione
    g = v.giocatore
    mia = stato.mia
    stella = {2: " ◎◎", 1: " ◎", -1: " ✕", -2: " ✕✕"}.get(c.preferenza, "")
    righe = [
        f"<b>{g.nome.upper()}</b>{stella}  <i>{g.squadra}</i> · {NOMI_RUOLO[g.ruolo]}",
    ]

    # Cercarlo per nome deve funzionare comunque — se il banditore lo chiama,
    # tu vuoi sapere cosa ne penso — ma la prima cosa da leggere e' che quel
    # nome, secondo il tuo stesso foglio, non e' piu' in Serie A.
    if not g.in_lista:
        righe.append(
            "\n<b>FUORI LISTA</b>\n<i>Nel listone c'e' ancora, nel tuo file "
            "delle fasce no: molto probabilmente e' andato via. Non lo "
            "consiglio e non lo conto nei prezzi.</i>"
        )

    # La prima riga e' quella che leggi davvero: non il tuo limite teorico ma
    # la cifra da dire ad alta voce per portarlo a casa.
    if c.massimo <= 0:
        righe.append(f"\n<b>NON OFFRIRE</b>  <i>({GIUDIZI[c.giudizio]})</i>")
    elif c.serve > c.massimo:
        righe.append(
            f"\n<b>TI SUPERERANNO</b>\n"
            f"<code>servono ~{c.serve}, tu puoi arrivare a {c.massimo}</code>"
        )
    else:
        righe.append(f"\n<b>DOVREBBE BASTARE: {c.serve}</b>  <i>({GIUDIZI[c.giudizio]})</i>")
        righe.append(f"<code>non superare {c.massimo}</code>")

    righe.append(
        f"<code>vale {v.valore:>5.0f} · costa ora {c.prezzo_corrente:>5.0f} · "
        f"base {g.quota}</code>"
    )

    if g.squalificato >= 1:
        quante = g.squalificato
        righe.append(
            f"\n<b>⛔ SQUALIFICATO — {quante} giornat"
            f"{'a' if quante == 1 else 'e'}</b>"
        )
    elif g.diffidato:
        righe.append("\n<i>⚠ diffidato: un altro giallo e salta una giornata.</i>")

    righe.extend(riga_infortunio(g))

    if c.motivi:
        righe.append("")
        righe.extend(f"· {m}" for m in c.motivi[:3])

    righe.extend(stato_campo(g))

    if len(c.rivali) > 1:
        nomi = ", ".join(f"{r.squadra.nome} ({r.massimo})" for r in c.rivali[:3])
        coda = f" e altri {len(c.rivali) - 3}" if len(c.rivali) > 3 else ""
        righe.append(f"\n<b>Chi te lo contende</b>\n<i>{nomi}{coda}</i>")

    righe.append(
        f"\n<b>Rendimento atteso</b>\n"
        f"<code>{_fm(v.fantamedia_attesa)} di fantamedia su "
        f"{v.presenze_attese:.0f} presenze</code>"
    )
    righe.append(
        f"<i>{v.rango_ruolo}º {NOMI_RUOLO[g.ruolo].lower()} per valore · "
        f"fascia {v.fascia if v.fascia < 5 else 'fuori listone'}</i>"
    )
    righe.extend(riga_continuita(v))
    righe.extend(riga_giudizi(g))
    if v.scommessa:
        righe.append(
            "<i>⚠ stima poco affidabile: poche partite alle spalle, "
            "il numero viene quasi tutto dal mercato</i>"
        )

    concluse = [s for s in g.storico if s.completa]
    if concluse:
        righe.append("\n<b>Come ha fatto</b>")
        for s in concluse[:2]:
            bonus = []
            if s.gol:
                bonus.append(f"{s.gol} gol")
            if s.assist:
                bonus.append(f"{s.assist} assist")
            if s.rigori_calciati:
                bonus.append(f"{s.rigori_calciati} rigori")
            coda = f" · {', '.join(bonus)}" if bonus else ""
            # Il club di allora si mostra solo se e' cambiato: quei voti li ha
            # presi da un'altra parte, ed e' un pezzo di contesto che cambia
            # come si legge la riga.
            dove = f" {s.squadra}" if s.squadra and s.squadra != g.squadra else "     "
            righe.append(
                f"<code>{s.stagione}{dove} {s.presenze:>2}pg  "
                f"fm {_fm(s.fantamedia)}</code>{coda}"
            )
    else:
        righe.append("\n<i>Nessuna presenza in Serie A: la stima viene dal mercato.</i>")

    if mia is not None:
        mancanti = stato.slot_mancanti(mia)
        righe.append(
            f"\n<code>hai {stato.crediti_residui(mia)} crediti · "
            f"{stato.slot_mancanti_totali(mia)} slot "
            "("
            + " ".join(f"{SIMBOLO_RUOLO[r]}{mancanti[r]}" for r in RUOLI if mancanti[r])
            + ")</code>"
        )
    return "\n".join(righe)


def turno(stato: StatoAsta, indice: int, reparto: str = "") -> str:
    """Di chi e' la chiamata adesso, e cosa conviene chiamare se tocca a te."""
    chiama = stato.chi_chiama(indice, reparto or None)
    if chiama is None:
        return "<b>Asta finita</b>\n<i>Nessuno puo' piu' chiamare.</i>"

    dove = f" — reparto {PLURALE_RUOLO[reparto].lower()}" if reparto else ""
    righe = [f"<b>Chiama {chiama.nome}</b>{dove}"]

    # Chi e' stato saltato, e perche'. E' l'informazione che nessuno tiene a
    # mente e che cambia i prezzi: ogni squadra fuori dal giro e' un rilancio
    # in meno su tutto quello che viene dopo.
    fuori = [
        s.nome
        for s in stato.squadre
        if not stato.puo_chiamare(s, reparto or None)
    ]
    if fuori:
        motivo = "hanno chiuso il reparto" if reparto else "hanno la rosa piena"
        righe.append(f"<i>Saltati ({motivo}): {', '.join(fuori)}</i>")

    prossimo = stato.squadre[stato.prossimo_turno(indice, reparto or None)]
    righe.append(f"<i>Poi tocca a {prossimo.nome}.</i>")

    soli = stato.reparti_solo_miei()
    if soli:
        quali = ", ".join(PLURALE_RUOLO[r].lower() for r in soli)
        righe.append(
            f"\n<b>Sei l'unico che cerca ancora: {quali}.</b>\n"
            "<i>Da adesso quel reparto lo chiudi tu al prezzo di base: chiama "
            "i migliori rimasti, non i piu' economici.</i>"
        )

    if chiama.e_mia:
        candidati = stato.da_chiamare(limite=5, reparto=reparto or None)
        if candidati:
            righe.append("")
            righe.append(consigli("Chiama uno di questi", candidati))
    return "\n".join(righe)


def campo_squadra(stato: StatoAsta, ruolo: str | None = None) -> str:
    """Chi gioca e chi no, fra i giocatori ancora liberi.

    Ordinato per minuti e non per valore: qui la domanda non e' chi rende di
    piu', e' chi c'e'. Serve a due momenti opposti — trovare il titolare che
    nessuno ha ancora chiamato, e accorgersi che il nome famoso in lista non
    scende in campo da tre giornate.
    """
    liberi = [
        v
        for v in stato.disponibili()
        if (not ruolo or v.giocatore.ruolo == ruolo) and v.giocatore.campo is not None
    ]
    if not liberi:
        return (
            "<b>Chi sta giocando</b>\n<i>Non ho i minuti giocati. "
            "Lancia /aggiorna.</i>"
        )
    giornate = max(v.giocatore.campo.giornate for v in liberi)
    liberi.sort(key=lambda v: (-v.giocatore.campo.quota_minuti, -v.valore))
    titolo = f"<b>Chi sta giocando</b> — {giornate}ª giornata"
    if ruolo:
        titolo += f", {PLURALE_RUOLO[ruolo].lower()}"

    righe = [titolo, "<code>   nome           min  costa vale</code>"]
    for v in liberi[:14]:
        g = v.giocatore
        righe.append(
            f"<code>{segno_campo(g)}{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:13]:<13} "
            f"{g.campo.minuti:>4} {v.prezzo_mercato:>5.0f} {v.valore:>4.0f}</code>"
        )

    fermi = sorted(
        (v for v in liberi if v.giocatore.campo.presenze == 0), key=lambda v: -v.valore
    )
    # Chi non ha giocato ED E' DATO TITOLARE e' il caso che vale di piu':
    # e' l'unica forma in cui si vede un titolare che rientra, e metterlo
    # nella lista delle riserve sprecherebbe l'unica informazione che il bot
    # ha su di lui.
    rientri = [v for v in fermi if v.giocatore.campo.previsto_titolare]
    riserve = [v for v in fermi if not v.giocatore.campo.previsto_titolare]
    if rientri:
        nomi = ", ".join(v.giocatore.nome for v in rientri[:6])
        righe.append(
            f"\n<b>Fermi, ma dati titolari nella prossima</b>\n<i>{nomi}</i>\n"
            "<i>E' il momento in cui costano meno di quanto varranno.</i>"
        )
    if riserve:
        nomi = ", ".join(v.giocatore.nome for v in riserve[:6])
        righe.append(
            f"\n<b>Non hanno ancora giocato</b>\n<i>{nomi}</i>\n"
            "<i>Puo' voler dire infortunio o riserva: il bot non sa quale, "
            "e li vale molto meno finche' non li vede in campo.</i>"
        )
    return "\n".join(righe)


def infortunati(stato: StatoAsta) -> str:
    """Chi e' fermo fra i giocatori ancora liberi, dal piu' lungo.

    Serve a due cose opposte nella stessa lista, ed e' per questo che sta
    tutta insieme: evitare di pagare pieno chi non giochera' per tre mesi, e
    accorgersi di chi rientra fra due settimane mentre il tavolo lo tratta
    come un infortunato qualunque.
    """
    fermi = [
        v
        for v in stato.disponibili()
        if v.giocatore.fermo is not None and v.giocatore.fermo.giornate_fuori > 0
    ]
    if not fermi:
        return "<b>Infortunati</b>\n<i>Nessuno fra i liberi, o manca /aggiorna.</i>"
    fermi.sort(key=lambda v: (-v.giocatore.fermo.giornate_fuori, -v.valore))

    righe = [
        "<b>Chi e' fermo, fra i liberi</b>",
        "<code>   nome          fuori costa vale</code>",
    ]
    for v in fermi[:16]:
        g = v.giocatore
        righe.append(
            f"<code>{SIMBOLO_RUOLO[g.ruolo]}  {g.nome[:13]:<13} "
            f"{g.fermo.giornate_fuori:>4}g {v.prezzo_mercato:>5.0f} {v.valore:>4.0f}</code>"
        )

    # Chi rientra presto ed e' comunque forte: il mercato sconta "infortunato"
    # senza guardare per quanto, e la differenza fra due giornate e tre mesi
    # e' tutto il margine che c'e' qui dentro.
    presto = [v for v in fermi if v.giocatore.fermo.giornate_fuori <= 3 and v.affare > 0.2]
    presto.sort(key=lambda v: -v.scarto)
    if presto:
        nomi = ", ".join(
            f"{v.giocatore.nome} ({v.giocatore.fermo.giornate_fuori}g)" for v in presto[:5]
        )
        righe.append(
            f"\n<b>Rientrano subito e costano da infortunati</b>\n<i>{nomi}</i>"
        )
    return "\n".join(righe)


def elenco(titolo: str, voci: list[tuple[Valutazione, float, int]]) -> str:
    """Una lista di giocatori: valutazione, prezzo corrente, massimo consigliato."""
    if not voci:
        return f"<b>{titolo}</b>\n<i>Nessun giocatore da mostrare.</i>"
    righe = [f"<b>{titolo}</b>", "<code> ruolo nome           costa  max</code>"]
    for v, prezzo, massimo in voci:
        g = v.giocatore
        righe.append(
            f"<code>{segno_campo(g)}{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:14]:<14} "
            f"{prezzo:>5.0f} {massimo:>4}</code>"
        )
    return "\n".join(righe)


def consigli(titolo: str, consigli_: list[Consiglio], coda: str = "") -> str:
    """Una lista di giocatori con la cifra che serve e quanto ci guadagni."""
    if not consigli_:
        return f"<b>{titolo}</b>\n<i>Niente da consigliare adesso.</i>"
    righe = [f"<b>{titolo}</b>", "<code>    nome         serve  max  rivali</code>"]
    avvisa = False
    for c in consigli_:
        g = c.valutazione.giocatore
        segno = "◎" if c.preferenza > 0 else " "
        campo = segno_campo(g)
        avvisa = avvisa or campo != " "
        righe.append(
            f"<code>{campo}{segno}{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:12]:<12} "
            f"{c.serve:>5} {c.massimo:>4}  {len(c.rivali):>4}</code>"
        )
    if avvisa:
        righe.append("\n<i>✕ non ha ancora giocato · &#183; finora subentra</i>")
    if coda:
        righe.append(f"\n<i>{coda}</i>")
    return "\n".join(righe)


def lista_obiettivi(stato: StatoAsta, righe_lista: list[tuple]) -> str:
    """Gli obiettivi dichiarati, con lo stato di ognuno.

    A meta' asta serve sapere due cose di ogni nome che avevi in mente: se e'
    ancora libero, e quanto costa adesso - non quanto costava quando l'hai
    scritto.
    """
    if not righe_lista:
        return (
            "<b>La tua lista e' vuota.</b>\n\n"
            "Cerca un giocatore e tocca <b>◎ Obiettivo</b> sotto la scheda, "
            "oppure scrivi <code>/target vlahovic</code>.\n"
            "<i>Un obiettivo alza le offerte del 15%, due volte del 35%.</i>"
        )
    voluti = [r for r in righe_lista if r[1] > 0]
    evitati = [r for r in righe_lista if r[1] < 0]
    out = []
    if voluti:
        out.append("<b>I tuoi obiettivi</b>")
        out.append("<code>   nome           serve  stato</code>")
        for v, grado, preso_da, serve in voluti:
            g = v.giocatore
            stato_txt = f"→ {preso_da}"[:12] if preso_da else f"libero ({serve})"
            out.append(
                f"<code>{'◎' * grado:<2}{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:13]:<13} "
                f"{stato_txt}</code>"
            )
    if evitati:
        out.append("\n<b>Da evitare</b>")
        out.extend(
            f"<code>✕  {SIMBOLO_RUOLO[v.giocatore.ruolo]} {v.giocatore.nome[:16]}</code>"
            for v, _, _, _ in evitati
        )
    return "\n".join(out)


def riepilogo(stato: StatoAsta, squadra: Squadra) -> str:
    """Come sta andando la tua asta, in numeri onesti."""
    r = stato.riepilogo(squadra)
    righe = [
        f"<b>{squadra.nome}</b>",
        f"<code>{int(r['giocatori'])}/{stato.parametri.slot_per_squadra} giocatori · "
        f"{int(r['speso'])} spesi · {int(r['residui'])} residui</code>",
        "",
        f"<code>valore comprato   {r['valore']:>6.0f}</code>",
        f"<code>speso             {int(r['speso']):>6}</code>",
    ]
    scarto = r["scarto"]
    if scarto >= 0:
        righe.append(
            f"\n<b>Hai comprato {scarto:.0f} crediti di valore in piu' di quanto "
            f"hai speso.</b>"
        )
    else:
        righe.append(
            f"\n<b>Hai pagato {-scarto:.0f} crediti sopra il valore di quello che hai "
            f"preso.</b>"
        )
    if r["giocatori"] < stato.parametri.slot_per_squadra:
        righe.append(
            "<i>L'asta non e' finita: il conto definitivo si legge alla fine, "
            "quando i crediti che avanzano valgono zero.</i>"
        )
    return "\n".join(righe)


def rosa(stato: StatoAsta, squadra: Squadra) -> str:
    mancanti = stato.slot_mancanti(squadra)
    righe = [
        f"<b>{squadra.nome}</b>",
        f"<code>{squadra.spesa()} spesi · {stato.crediti_residui(squadra)} residui · "
        f"{len(squadra.acquisti)}/{stato.parametri.slot_per_squadra} giocatori</code>",
    ]
    for ruolo in RUOLI:
        presi = [a for a in squadra.acquisti if a.ruolo == ruolo]
        presi.sort(key=lambda a: -a.prezzo)
        totale = sum(a.prezzo for a in presi)
        righe.append(
            f"\n<b>{PLURALE_RUOLO[ruolo]}</b> "
            f"<i>{len(presi)}/{stato.parametri.slot[ruolo]} · {totale} crediti</i>"
        )
        if presi:
            righe.extend(f"<code>{a.prezzo:>3}  {a.nome}</code>" for a in presi)
        if mancanti[ruolo]:
            righe.append(f"<i>ne mancano {mancanti[ruolo]}</i>")
    return "\n".join(righe)


def budget(stato: StatoAsta) -> str:
    mia = stato.mia
    if mia is None:
        return "Non trovo la tua squadra. Usa /setup."
    piano = stato.piano_spesa()
    mancanti = stato.slot_mancanti(mia)
    righe = [
        "<b>Come spendere quello che ti resta</b>",
        f"<code>{stato.crediti_residui(mia)} crediti · "
        f"{stato.slot_mancanti_totali(mia)} slot da riempire</code>",
        "",
        "<code>reparto        slot  crediti  a testa</code>",
    ]
    for ruolo in RUOLI:
        if mancanti[ruolo] <= 0:
            righe.append(f"<code>{PLURALE_RUOLO[ruolo]:<14} completo</code>")
            continue
        a_testa = piano[ruolo] / mancanti[ruolo]
        righe.append(
            f"<code>{PLURALE_RUOLO[ruolo]:<14} {mancanti[ruolo]:>4}  "
            f"{piano[ruolo]:>7}  {a_testa:>7.0f}</code>"
        )
    infl = stato.inflazione()
    righe.append("")
    righe.append(_frase_inflazione(infl))
    return "\n".join(righe)


def _frase_inflazione(infl: float) -> str:
    scarto = (infl - 1) * 100
    if infl >= 1.15:
        return (
            f"<b>Mercato caro: +{scarto:.0f}%.</b> In sala restano piu' crediti che "
            "giocatori validi: chi compra adesso paga il conto degli altri. "
            "Aspetta, e prendi i tuoi quando la cassa si svuota."
        )
    if infl <= 0.9:
        return (
            f"<b>Mercato a sconto: {scarto:.0f}%.</b> I crediti sono finiti prima dei "
            "giocatori: adesso si fanno gli affari, alza la mano."
        )
    return f"<b>Mercato in linea</b> ({scarto:+.0f}%): i prezzi correnti sono quelli giusti."


def _frase_pendenza(pendenza: float) -> str:
    """Che carattere ha questo tavolo, imparato dalle chiamate gia' fatte."""
    if pendenza >= 1.15:
        return (
            "<b>Qui i campioni si pagano sopra il listino.</b> Ho corretto i "
            "prezzi di conseguenza: sui big ti diro' cifre piu' alte, e piu' "
            "spesso di lasciar perdere. Il valore si raccoglie nella fascia "
            "media, che in un tavolo cosi' si svende."
        )
    if pendenza <= 0.88:
        return (
            "<b>Qui i crediti si spalmano</b> invece di concentrarsi sui big: "
            "i campioni costano meno del listino, e prenderne uno vero e' la "
            "mossa che gli altri non stanno facendo."
        )
    return "<b>Prezzi in linea col listino</b>: questa lega compra come dice la carta."


def mercato(stato: StatoAsta) -> str:
    righe = ["<b>Stato dell'asta</b>", ""]
    righe.append("<code>squadra          crediti  slot</code>")
    for s in sorted(stato.squadre, key=lambda s: (not s.e_mia, s.nome)):
        segno = "*" if s.e_mia else " "
        righe.append(
            f"<code>{segno}{s.nome[:15]:<15} {stato.crediti_residui(s):>7}  "
            f"{stato.slot_mancanti_totali(s):>4}</code>"
        )
    righe.append("")
    righe.append(_frase_inflazione(stato.inflazione()))
    righe.append(_frase_pendenza(stato.pendenza_di_mercato()))

    mancanti_lega = stato.slot_mancanti_lega()
    righe.append("\n<b>Chi resta sopra il livello di rimpiazzo</b>")
    righe.append("<code>reparto        validi  da riempire</code>")
    for ruolo in RUOLI:
        validi = sum(
            1 for v in stato.disponibili() if v.giocatore.ruolo == ruolo and v.vorp > 0
        )
        righe.append(
            f"<code>{PLURALE_RUOLO[ruolo]:<14} {validi:>3}  {mancanti_lega[ruolo]:>10}</code>"
        )
    return "\n".join(righe)


def piano_testo(stato: StatoAsta, preferenze: dict[int, int]) -> str:
    """Il foglio da tenere accanto durante l'asta, in testo semplice.

    Un bot risponde bene a una domanda alla volta, ma all'asta serve anche
    l'altra cosa: lo sguardo d'insieme su un reparto intero, senza chiedere
    niente a nessuno. Questo e' quel foglio - si scarica, si stampa, e
    funziona anche se il telefono muore.
    """
    p = stato.parametri
    righe = [
        "PIANO D'ASTA — Fantabot",
        f"{p.crediti} crediti · {p.n_squadre} squadre · "
        f"{p.slot['p']}-{p.slot['d']}-{p.slot['c']}-{p.slot['a']}",
        "",
        "prezzo = quanto costera'   max = il tuo limite",
        "◎ = obiettivo   ! = stima poco affidabile",
        "",
    ]
    correnti = stato.prezzi_correnti()
    for ruolo in RUOLI:
        dentro = [
            v
            for v in stato.disponibili()
            if v.giocatore.ruolo == ruolo and v.fascia < 5
        ]
        dentro.sort(key=lambda v: -v.valore)
        spesa = sum(correnti.get(v.giocatore.id_fc, 1.0) for v in dentro)
        righe.append("=" * 58)
        righe.append(
            f"{PLURALE_RUOLO[ruolo].upper()} — {len(dentro)} da comprare in lega, "
            f"{spesa:.0f} crediti in ballo"
        )
        righe.append("=" * 58)
        righe.append(f"{'':2}{'nome':<16}{'sq':<5}{'prezzo':>7}{'max':>6}{'fm':>7}{'pres':>6}")
        for v in dentro:
            g = v.giocatore
            c = stato.consiglia(g.id_fc)
            segni = ("◎" if preferenze.get(g.id_fc, 0) > 0 else " ") + (
                "!" if v.scommessa else " "
            )
            righe.append(
                f"{segni}{g.nome[:15]:<16}{g.squadra:<5}"
                f"{correnti.get(g.id_fc, 1.0):>7.0f}"
                f"{(c.massimo if c else 0):>6}"
                f"{_fm(v.fantamedia_attesa):>7}{v.presenze_attese:>6.0f}"
            )
        righe.append("")
    return "\n".join(righe)


def aiuto(completo: bool = False) -> str:
    """Cosa serve adesso, non tutto quello che il bot sa fare.

    TRENTA COMANDI NON SONO TRENTA POSSIBILITA': sono trenta cose da
    ricordare mentre il banditore aspetta, e il risultato e' che non se ne usa
    nessuna. Qui in cima ce ne sono tre — chiamare, chiedere una cifra,
    registrare — perche' sono quelle che si usano ogni trenta secondi. Il
    resto esiste ancora e sta sotto `/aiuto tutto`, dove lo si legge con
    calma il giorno prima.
    """
    breve = (
        "<b>Fantabot</b> — assistente d'asta\n\n"
        "<b>Ti bastano queste tre.</b>\n\n"
        "<code>/chiama</code>\n"
        "<i>Cosa chiamare adesso: il reparto in ballo, chi ti conviene, e "
        "se non conviene nessuno, l'esca per far spendere gli altri.</i>\n\n"
        "<code>vlahovic</code>\n"
        "<i>La scheda e fino a quanto offrire. Basta il nome, anche storpiato.</i>\n\n"
        "<code>+vlahovic 25</code>\n"
        "<i>L'ho preso io a 25. Se lo prende un altro: "
        "<code>vlahovic 25 marco</code>.</i>\n\n"
        "<b>Se sbagli</b>  /annulla  ·  /correggi <code>vlahovic 32</code>\n"
    )
    if not completo:
        return breve + "\n<i>Tutti gli altri comandi: /aiuto tutto</i>"

    return (
        breve
        + "\n<b>Mentre l'asta corre</b>\n"
        "/rosa — la tua rosa (o /rosa <code>marco</code>)\n"
        "/budget — quanto spendere per reparto\n"
        "/mercato — crediti e slot di tutti, inflazione\n"
        "/liberi <code>d</code> — i migliori difensori ancora liberi\n"
        "/occasioni — chi rende piu' di quanto costa\n"
        "/turno — a chi tocca chiamare\n"
        "/reparto <code>p</code> — apri i portieri (<code>libero</code> per togliere)\n"
        "/coppie — come abbinare portieri e attaccanti\n"
        "/riepilogo — quanto valore hai comprato, e a che prezzo\n"
        "/piano — il foglio d'asta da stampare\n"
        "\n<b>La tua lista</b>\n"
        "/target <code>vlahovic</code> — obiettivo: offro di piu'\n"
        "/evita <code>vlahovic</code> — offro di meno\n"
        "/lista — i tuoi obiettivi, chi e' libero e a quanto\n"
        "\n<b>Durante la stagione</b>\n"
        "/formazione — chi schierare, e con che modulo\n"
        "/giornata — il calendario, con dentro i tuoi\n"
        "/campo — chi sta giocando davvero\n"
        "/infortunati — chi e' fermo e per quanto\n"
        "/squalificati — chi salta la prossima, e i diffidati\n"
        "/andamento <code>malen</code> — bonus e malus giornata per giornata\n"
        "/scambi — gli scambi che convengono anche all'altro\n"
        "/scambio <code>malen marco</code> — registra un passaggio\n"
        "\n<b>Configurazione</b>\n"
        "/setup <code>500 8 3-8-8-6</code> — crediti, squadre, slot\n"
        "/squadre <code>Marco, Luca...</code> — nomi degli avversari\n"
        "/squadre mia <code>CarmySpecial</code> — il nome della tua\n"
        "/prudenza <code>1.2</code> — piu' alto = offerte piu' caute\n"
        "/importa — come mandarmi il foglio delle fasce\n"
        "/fuorilista — chi ho smesso di nominare, e perche'\n"
        "/aggiorna — rileggi le fonti\n"
        "/azzera — cancella le rose e ricomincia\n"
    )


def esito_import(esito) -> str:
    """Cosa ha capito il bot dal foglio che gli hai mandato.

    Un import che sbaglia in silenzio la sera dell'asta e' peggio di un import
    che non parte: qui si dichiara sempre quali colonne sono state usate e
    quanti nomi non sono stati riconosciuti.
    """
    if esito.errore:
        return (
            f"<b>Non ce l'ho fatta.</b>\n{esito.errore}\n\n"
            "<i>Serve un foglio con una colonna dei nomi e almeno una fra "
            "prezzo medio d'asta, prezzo massimo o fascia.</i>"
        )
    nomi = {
        "prezzo_medio": "prezzi medi d'asta",
        "prezzo_max": "prezzi massimi",
        "fascia": "fasce",
        "squadra": "squadre",
        "ruolo": "ruoli",
        "nome": "nomi",
    }
    usate = [
        f"<code>{colonna}</code> → {nomi.get(campo, campo)}"
        for campo, colonna in esito.colonne_usate.items()
    ]
    righe = [
        "<b>Importato.</b>",
        f"<code>{esito.abbinati} giocatori riconosciuti su {esito.righe_lette}</code>",
    ]
    if esito.con_prezzo:
        righe.append(
            f"<code>{esito.con_prezzo} con il prezzo medio pagato nelle aste</code>\n"
            "<i>Da adesso quel numero prende il posto della mia stima: "
            "e' un dato osservato, non un'ipotesi.</i>"
        )
    if esito.con_fascia:
        righe.append(f"<code>{esito.con_fascia} con la fascia</code>")
    righe.append("\n<b>Colonne che ho usato</b>\n" + "\n".join(usate))
    if esito.non_trovati:
        righe.append(
            "\n<b>Non ho riconosciuto questi nomi</b>\n<i>"
            + ", ".join(esito.non_trovati[:8])
            + ("…" if len(esito.non_trovati) > 8 else "")
            + "</i>\nControlla che sia lo stesso listone: /aggiorna lo riallinea."
        )
    return "\n".join(righe)


def chiamata(
    reparto: str | None,
    scelte: list,
    esche: list,
    stato: StatoAsta,
    chiuso: str = "",
) -> str:
    """Il messaggio che leggi quando tocca a te chiamare.

    UNO SOLO, e in ordine di decisione. Prima cosa si sta chiamando — il
    reparto — poi chi prendere, poi, se prendere non conviene, chi chiamare
    per far spendere gli altri. Tre schermate separate obbligavano a
    ricomporre la situazione in testa mentre il banditore aspetta, ed e'
    esattamente quello che all'asta non si ha tempo di fare.
    """
    mia = stato.mia
    righe: list[str] = []
    if chiuso:
        righe.append(
            f"<b>Reparto {PLURALE_RUOLO[chiuso].lower()} chiuso.</b> "
            f"Si passa ai {PLURALE_RUOLO[reparto].lower() if reparto else '—'}."
        )
    if reparto:
        mancanti = stato.slot_mancanti(mia)[reparto] if mia else 0
        ancora = sum(
            stato.slot_mancanti(s).get(reparto, 0) for s in stato.squadre
        )
        righe.append(
            f"<b>Si chiamano {PLURALE_RUOLO[reparto].lower()}</b>"
            f"  <i>te ne mancano {mancanti}, alla lega {ancora}</i>"
        )
    else:
        righe.append(
            "<b>Chiamata libera</b>  <i>ogni reparto e' aperto</i>\n"
            "<i>Se la tua asta va a reparti — prima i portieri, poi i "
            "difensori — accendilo con <code>/reparto p</code>: da li' in poi "
            "avanza da solo.</i>"
        )
    if mia is not None:
        righe.append(
            f"<code>hai {stato.crediti_residui(mia)} crediti · "
            f"{stato.slot_mancanti_totali(mia)} slot</code>"
        )

    if scelte:
        righe.append("\n<b>Chiama uno di questi</b>")
        righe.append("<code>   nome            serve  vale</code>")
        for c in scelte:
            g = c.valutazione.giocatore
            righe.append(
                f"<code>{segno_campo(g)}{SIMBOLO_RUOLO[g.ruolo]} "
                f"{g.nome[:14]:<14} {c.serve:>5} {c.valutazione.valore:>5.0f}</code>"
                f"  <i>{len(c.rivali)} rivali</i>"
            )
    else:
        righe.append(
            "\n<b>Niente che convenga chiamare adesso.</b>\n"
            "<i>Tutto quello che ti serve costa piu' di quanto vale: e' il "
            "momento di far spendere gli altri.</i>"
        )

    if esche:
        righe.append("\n<b>Oppure un'esca — falli spendere</b>")
        for e in esche:
            g = e.valutazione.giocatore
            righe.append(
                f"<code>{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:14]:<14} "
                f"~{e.drenati:>3} crediti</code>  <i>{len(e.rivali)} lo vogliono</i>"
            )
        righe.append(f"<i>{esche[0].rischio}.</i>")
    return "\n".join(righe)


def squadre_rinominate(esito, nome_mia: str = "") -> str:
    """Chi ha preso quale nome, e cosa e' rimasto fuori.

    «Rinominate 7 squadre» su otto nomi dati e' un numero che non spiega
    niente: sembra un errore di conteggio ed e' invece la squadra tua, che nel
    conto c'e' ma fra gli avversari no. Qui si dice a chi sono andati i nomi e
    cosa e' avanzato, cosi' il numero non ha bisogno di essere interpretato.
    """
    righe = [f"<b>Rinominati {len(esito.assegnati)} avversari</b>"]
    if esito.assegnati:
        righe.append("<code>" + " · ".join(esito.assegnati) + "</code>")
    if esito.senza_nome:
        righe.append(
            f"\n<i>{esito.senza_nome} avversari sono rimasti col nome di prima: "
            "aggiungi gli altri nomi quando li sai.</i>"
        )
    if esito.avanzati:
        avanzati = ", ".join(esito.avanzati)
        righe.append(
            f"\n<b>Non ho usato: {avanzati}</b>\n"
            f"<i>Gli avversari sono {len(esito.assegnati)}, non uno di piu': "
            "l'ultima squadra della lega e' la tua"
            + (f", che si chiama «{nome_mia}»." if nome_mia else ".")
            + "</i>\n<i>Se quel nome era per te: "
            f"<code>/squadre mia {esito.avanzati[0]}</code></i>"
        )
    return "\n".join(righe)


def conferma_azzera(perso: dict, nome_lega: str = "") -> str:
    """Cosa sparisce, prima di far sparire qualcosa.

    Una conferma che non dice i numeri non e' una domanda, e' un ostacolo: si
    clicca senza leggere. Qui invece si legge quanto si butta, e se non c'e'
    niente da buttare lo si dice invece di chiedere.
    """
    if not perso.get("acquisti") and not perso.get("preferenze"):
        return (
            "<b>Non c'e' niente da azzerare.</b>\n"
            "<i>Nessun acquisto registrato e nessun obiettivo.</i>"
        )
    righe = ["<b>Azzero l'asta?</b>", ""]
    if perso.get("acquisti"):
        righe.append(
            f"<code>{perso['acquisti']} acquisti  ·  "
            f"{perso['crediti']} crediti spesi</code>"
        )
    if perso.get("preferenze"):
        righe.append(f"<code>{perso['preferenze']} fra obiettivi ed evitati</code>")
    righe += [
        "",
        "<b>Restano:</b> le regole della lega, i nomi degli avversari, il "
        "foglio delle fasce che hai caricato, e tutti i dati sui giocatori.",
        "",
        "<i>Si cancellano solo le rose. Non si torna indietro.</i>",
    ]
    return "\n".join(righe)


def azzerata(perso: dict) -> str:
    return (
        "<b>Asta azzerata.</b>\n"
        f"<code>via {perso.get('acquisti', 0)} acquisti e "
        f"{perso.get('preferenze', 0)} preferenze</code>\n\n"
        "<i>Le regole e il foglio delle fasce sono al loro posto: puoi "
        "ricominciare subito.</i>"
    )


def dati_da_fuori(quando: str) -> str:
    """La risposta a /aggiorna dove le fonti le legge qualcun altro.

    Non e' un errore e non deve sembrarlo: e' come funziona. Serve solo dire
    di quando sono i dati — che e' la domanda vera dietro «aggiorna» — e ogni
    quanto arrivano i prossimi.
    """
    return (
        "<b>I dati arrivano da soli.</b>\n"
        f"<code>ultimi ricevuti: {quando[:16] or 'mai'}</code>\n\n"
        "<i>Da qui non riesco a leggere fantacalcio.it: chi mi ospita lascia "
        "uscire solo verso Telegram. Le fonti le rilegge GitHub Actions ogni "
        "sei ore e mi manda il risultato gia' pronto, quindi non c'e' niente "
        "da lanciare a mano.</i>"
    )


def fuori_lista(righe: list, quanti_nel_listone: int = 0) -> str:
    """Chi il listone ha ancora e il file delle fasce no.

    Si mostra con i minuti giocati accanto, e quella colonna e' il controllo:
    chi e' andato via non ne ha nessuno, e vederne uno con centottanta minuti
    vuol dire che il suo nome nelle fasce e' scritto in un altro modo — non
    che ha cambiato campionato.
    """
    if not righe:
        return (
            "<b>Nessuno fuori lista.</b>\n"
            "<i>O il file delle fasce non e' ancora arrivato: senza, non tolgo "
            "nessuno.</i>"
        )
    testa = [
        "<b>Fuori lista — non li nomino piu'</b>",
        f"<code>{len(righe)} nel listone su {quanti_nel_listone or '?'} "
        "non ci sono nelle fasce</code>",
        "<code>   nome            da   fvm   min</code>",
    ]
    for r in righe[:20]:
        testa.append(
            f"<code>{SIMBOLO_RUOLO.get(r['ruolo'], ' ')}  {r['nome'][:15]:<15} "
            f"{r['squadra']:<4} {r['fvm']:>4} {r['minuti']:>5}</code>"
        )
    if len(righe) > 20:
        testa.append(f"<i>…e altri {len(righe) - 20}.</i>")
    giocano = [r for r in righe if r["minuti"] > 0]
    if giocano:
        testa.append(
            f"\n<b>Attenzione: {len(giocano)} hanno giocato davvero</b>\n<i>"
            + ", ".join(f"{r['nome']} ({r['minuti']}')" for r in giocano[:6])
            + "</i>\nSe uno di questi ti serve, e' il nome che non combacia: "
            "aggiungilo al foglio e rimandamelo."
        )
    return "\n".join(testa)


def stato_import(riassunto: dict) -> str:
    """Cosa c'e' gia' importato, e come si importa."""
    quante = riassunto.get("righe") or 0
    if not quante:
        return (
            "<b>Nessun listino esterno importato.</b>\n\n"
            "Se usi <b>FantaLab</b> (o un tool simile) puoi mandarmi qui il "
            "foglio con i prezzi medi d'asta e le tue fasce: "
            "<i>Strategia → Esporta in Excel</i>, poi allega il file in questa "
            "chat.\n\n"
            "Il prezzo medio pagato nelle aste vere e' l'unica cosa che io "
            "posso soltanto stimare: se ce l'hai, la mia stima si fa da parte."
        )
    return (
        f"<b>Listino esterno attivo</b>\n"
        f"<code>{quante} giocatori · {riassunto.get('prezzi') or 0} con prezzo "
        f"· {riassunto.get('fasce') or 0} con fascia</code>\n"
        f"<code>fonte: {riassunto.get('fonte') or '—'} · "
        f"importato il {str(riassunto.get('quando') or '')[:16]}</code>\n\n"
        "<i>Per aggiornarlo, mandami un foglio nuovo.</i>"
    )


# -- la stagione ----------------------------------------------------------


def squalificati(stato: StatoAsta) -> str:
    """Chi salta la prossima e chi rischia quella dopo, i tuoi per primi.

    Le due liste stanno insieme e restano distinte: una toglie un giocatore
    dalla formazione di domenica, l'altra non toglie niente adesso e serve a
    non farsi trovare impreparati la settimana dopo — che e' la sola cosa che
    la diffida puo' dirti in anticipo.
    """
    mia = stato.mia
    miei = {a.id_fc for a in mia.acquisti} if mia is not None else set()

    def elenca(quali, titolo: str) -> list[str]:
        if not quali:
            return []
        quali.sort(key=lambda v: (v.giocatore.id_fc not in miei, -v.valore))
        righe = [f"\n<b>{titolo}</b>"]
        for v in quali[:16]:
            g = v.giocatore
            stella = "★" if g.id_fc in miei else " "
            quante = f" {g.squalificato}g" if g.squalificato > 1 else "   "
            righe.append(
                f"<code>{stella}{SIMBOLO_RUOLO[g.ruolo]} {g.nome[:15]:<15} "
                f"{g.squadra}{quante}</code>"
            )
        return righe

    tutti = list(stato.valutazioni.values())
    fermi = [v for v in tutti if v.giocatore.squalificato >= 1]
    rischio = [v for v in tutti if v.giocatore.diffidato]
    if not fermi and not rischio:
        return (
            "<b>Squalificati e diffidati</b>\n"
            "<i>Nessuno, secondo fantacalcio.it. Dopo poche giornate e' "
            "normale: per una diffida servono quattro gialli.</i>"
        )
    righe = ["<b>Squalificati e diffidati</b>"]
    righe += elenca(fermi, "Saltano la prossima")
    righe += elenca(rischio, "Diffidati — un altro giallo e saltano quella dopo")
    if any(v.giocatore.id_fc in miei for v in fermi + rischio):
        righe.append("\n<i>★ sono i tuoi.</i>")
    return "\n".join(righe)


def contro_chi(s) -> str:
    """L'avversario in due caratteri e mezzo: sigla, e se si gioca fuori.

    Minuscolo per la trasferta e maiuscolo per la casa, senza legenda: e' la
    convenzione dei giornali sportivi da sempre, e una colonna che si legge
    senza spiegazione e' l'unica che si legge davvero.
    """
    a = getattr(s, "avversario", None)
    if a is None:
        return ""
    return a.sigla if a.in_casa else a.sigla.lower()


def calendario(
    partite: list, numero: int, avversari: dict, stato: StatoAsta, prima: int = 1
) -> str:
    """Il calendario di una giornata, con marcati i tuoi giocatori.

    Serve a due domande diverse: cosa si gioca, e dove stanno i miei. La
    seconda e' quella per cui esiste — una giornata con quattro dei tuoi in
    una sola partita e' un rischio che si vede solo guardando il calendario,
    mai guardando la rosa.
    """
    if not partite:
        return (
            f"<b>Giornata {numero}</b>\n<i>Non ho il calendario di questa "
            "giornata.</i>"
        )
    mia = stato.mia
    miei: dict[str, list[str]] = {}
    if mia is not None:
        for a in mia.acquisti:
            v = stato.valutazioni.get(a.id_fc)
            if v is not None:
                miei.setdefault(v.giocatore.squadra, []).append(v.giocatore.nome)

    quando = partite[0].data if partite[0].data else ""
    testa = [f"<b>Giornata {numero}</b>" + (f" — {quando}" if quando else "")]
    if numero < prima:
        testa.append(
            f"<i>La tua lega comincia dalla {prima}ª: questa e' gia' giocata.</i>"
        )
    for p in partite:
        dentro = miei.get(p.casa, []) + miei.get(p.ospite, [])
        marchio = "◆" if dentro else " "
        riga = f"<code>{marchio} {p.casa} - {p.ospite}</code>"
        if dentro:
            riga += f"  <i>{', '.join(dentro[:4])}</i>"
        testa.append(riga)

    # Dove si concentrano i tuoi: due squadre che si affrontano vogliono dire
    # che un tuo difensore e un tuo attaccante si tolgono i punti a vicenda.
    scontri = [
        p
        for p in partite
        if miei.get(p.casa) and miei.get(p.ospite)
    ]
    if scontri:
        testa.append("\n<b>Tuoi contro tuoi</b>")
        for p in scontri:
            testa.append(
                f"<i>{', '.join(miei[p.casa])} contro "
                f"{', '.join(miei[p.ospite])}</i>"
            )

    facili = sorted(
        ((sigla, a) for sigla, a in avversari.items() if sigla in miei),
        key=lambda t: t[1].difficolta,
    )
    if facili:
        testa.append("\n<b>Le tue partite, dalla piu' facile</b>")
        for sigla, a in facili[:6]:
            testa.append(
                f"<code>{sigla} {a.difficolta:+.2f}</code>  <i>{a.sigla} "
                f"{a.dove} — {', '.join(miei[sigla][:3])}</i>"
            )
    return "\n".join(testa)


def formazione(c, giornata: int = 0) -> str:
    """Gli undici da schierare, con accanto il perche' di ognuno."""
    if c is None:
        return (
            "<b>Formazione</b>\n<i>La rosa e' vuota: registra gli acquisti "
            "dell'asta e riprova.</i>"
        )
    quando = f" — {giornata}ª giornata" if giornata else ""
    righe = [
        f"<b>{c.nome_modulo}</b>{quando}",
        f"<i>{c.punti:.1f} punti attesi dagli undici</i>",
        "<code>   nome          contro  attesi</code>",
    ]

    def riga(s) -> str:
        return (
            f"<code>{SIMBOLO_RUOLO[s.ruolo]}  {s.nome[:13]:<13} "
            f"{contro_chi(s):<7} {s.punti:>5.1f}</code>  <i>{s.nota}</i>"
        )

    righe.extend(riga(s) for s in c.titolari)
    if c.panchina:
        righe.append("\n<b>Panchina, in ordine di ingresso</b>")
        righe.extend(riga(s) for s in c.panchina[:6])
    for avviso in c.avvisi:
        righe.append(f"\n<b>⚠</b> <i>{avviso}</i>")
    righe.append(
        "\n<i>«attesi» e' la fantamedia moltiplicata per quanto e' probabile "
        "che giochi: non e' un voto, e' un voto scontato dal rischio.</i>"
    )
    return "\n".join(righe)


def scambi(proposte: list, mia_nome: str = "tu") -> str:
    """Gli scambi che hanno senso sui numeri, con quanto guadagna anche l'altro."""
    if not proposte:
        return (
            "<b>Scambi</b>\n<i>Nessuno scambio uno-a-uno che convenga a "
            "entrambi. Succede quando le rose hanno gli stessi buchi.</i>"
        )
    righe = ["<b>Scambi che convengono a tutti e due</b>"]
    for s in proposte:
        righe.append(
            f"\n<b>Con {s.con.nome}</b>\n"
            f"<code>dai   {SIMBOLO_RUOLO[s.do.giocatore.ruolo]} "
            f"{s.do.giocatore.nome[:16]:<16} vale {s.do.valore:>4.0f}</code>\n"
            f"<code>prendi {SIMBOLO_RUOLO[s.prendo.giocatore.ruolo]} "
            f"{s.prendo.giocatore.nome[:16]:<16} vale {s.prendo.valore:>4.0f}</code>\n"
            f"<i>tu +{s.guadagno:.0f} · lui +{s.suo_guadagno:.0f}</i>"
        )
    righe.append(
        "\n<i>Il guadagno tiene conto dei buchi di ognuno: lo stesso "
        "centrocampista vale di piu' a chi ne ha tre scarsi che a chi ne ha "
        "otto buoni. Simpatie e rancori non sono nel conto.</i>"
    )
    righe.append(
        "<i>⚠ Dare via una riserva qui non costa niente, perche' una riserva "
        "non porta punti. Costa la domenica in cui un titolare si fa male: "
        "guarda /formazione prima di svuotare la panchina.</i>"
    )
    return "\n".join(righe)


def andamento_giocatore(nome: str, turni: list) -> str:
    """Giornata per giornata: bonus, malus e minuti, dal piu' recente."""
    if not turni:
        return (
            f"<b>{nome}</b>\n<i>Non ho ancora giornate registrate. "
            "Servono almeno due /aggiorna in giornate diverse.</i>"
        )
    righe = [f"<b>{nome} — giornata per giornata</b>",
             "<code>  g   fm   min  bonus/malus</code>"]
    for t in turni[:10]:
        pezzi = []
        if t.gol:
            pezzi.append(f"{t.gol} gol")
        if t.assist:
            pezzi.append(f"{t.assist} assist")
        if t.ammonizioni:
            pezzi.append(f"{t.ammonizioni} amm")
        if t.espulsioni:
            pezzi.append(f"{t.espulsioni} esp")
        if t.gol_subiti:
            pezzi.append(f"-{t.gol_subiti} subiti")
        fm = _fm(t.fantamedia) if t.fantamedia is not None else "  sv"
        etichetta = f"{t.giornata}ª" if t.coperte == 1 else f"{t.giornata}ª×{t.coperte}"
        righe.append(
            f"<code>{etichetta:>5} {fm:>6} {t.minuti:>4}</code>  "
            f"<i>{', '.join(pezzi) or '—'}</i>"
        )
    if any(t.coperte > 1 for t in turni[:10]):
        righe.append(
            "\n<i>«×2» vuol dire due giornate in una riga: il bot non ha letto "
            "in mezzo, e non le spalma per non inventare una domenica.</i>"
        )
    return "\n".join(righe)


def abbinamenti(elenco: list, ruolo: str, gia_mio=None, fasce=None) -> str:
    """Le coppie di calendario, tradotte in giocatori veri con i prezzi.

    `gia_mio` e' il giocatore che hai gia' comprato: allora la riga non mostra
    la coppia ma **solo chi manca, e solo quanto costa lui**. Sommare anche il
    prezzo di uno che hai gia' pagato darebbe una cifra che non devi spendere,
    proprio nel messaggio che serve a decidere quanto spendere.
    """
    articolo = "gli" if ruolo == "a" else "i"
    if not elenco:
        return (
            f"<b>Abbinamenti</b>\n<i>Non ho la tabella per {articolo} "
            f"{PLURALE_RUOLO.get(ruolo, ruolo).lower()}. "
            "Mandamela come file: prima riga e prima colonna con le sigle "
            "delle squadre, i punteggi dentro.</i>"
        )
    nomi_fascia = {1: "Top", 2: "Semi-Top", 3: "Terza", 4: "Quarta", 5: "Outsider"}
    titolo = f"<b>Come si abbinano {articolo} {PLURALE_RUOLO[ruolo].lower()}</b>"
    if fasce:
        titolo += f" — {nomi_fascia[fasce[0]]} + {nomi_fascia[fasce[1]]}"

    def compagno(x):
        primo = x.primo.giocatore.id_fc == gia_mio.giocatore.id_fc
        return x.secondo if primo else x.primo

    if gia_mio is not None:
        righe = [
            f"{titolo}\n<i>hai {gia_mio.giocatore.nome}: chi ci metti accanto</i>",
            "<code>voto  chi manca            costa</code>",
        ]
        for x in elenco:
            altro = compagno(x)
            righe.append(
                f"<code>{x.punteggio:>4}  {altro.giocatore.nome[:18]:<18} "
                f"{altro.prezzo_mercato:>5.0f}</code>"
            )
        conviene = min(elenco, key=lambda x: compagno(x).prezzo_mercato)
        if conviene is not elenco[0]:
            altro = compagno(conviene)
            righe.append(
                f"\n<b>A meno</b>: {altro.giocatore.nome}, "
                f"{conviene.punteggio} per {altro.prezzo_mercato:.0f} crediti."
            )
    else:
        righe = [titolo, "<code>voto  coppia                     costo</code>"]
        for x in elenco:
            a, b = x.primo.giocatore, x.secondo.giocatore
            coppia = f"{a.nome[:11]} + {b.nome[:11]}"
            righe.append(
                f"<code>{x.punteggio:>4}  {coppia:<26} {x.costo:>5.0f}</code>"
            )
        conviene = min(elenco, key=lambda x: x.costo)
        if conviene is not elenco[0]:
            a, b = conviene.primo.giocatore, conviene.secondo.giocatore
            righe.append(
                f"\n<b>Il piu' conveniente</b>: {a.nome} + {b.nome}, "
                f"{conviene.punteggio} a {conviene.costo:.0f} crediti."
            )

    righe.append(
        "\n<i>Il voto dice quanto i due calendari si alternano bene: quando uno "
        "ha la giornata difficile, l'altro ce l'ha facile. E' un numero di "
        "stagione, non di domenica — non dice quale dei due schierare.</i>"
    )
    return "\n".join(righe)
