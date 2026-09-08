"""Il bot Telegram: i comandi, i bottoni, e la strada piu' corta fra una
chiamata all'asta e una cifra da dire ad alta voce.

Tre modi di scrivere, in ordine di fretta:

* <code>vlahovic</code> — la scheda e il massimo da offrire;
* <code>+vlahovic 25</code> — l'ho preso io a 25, registrato e via;
* <code>vlahovic 25</code> — l'ha preso qualcun altro, un tap per dire chi.

Non c'e' nessuna conversazione a stati: durante un'asta un bot che aspetta la
risposta a una domanda fatta due giocatori fa e' un bot che ti fa perdere il
giocatore. Ogni messaggio si spiega da solo e ogni bottone porta con se' tutto
quello che serve per essere eseguito.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import impostazioni
from ..dati import andamento, calendario, coppie
from ..dati.aggiorna import aggiorna_tutto
from ..dati.esterno import importa, riassunto
from ..dati.magazzino import cerca
from ..db import connetti
from ..motore import formazione as fmz
from ..motore.valutazione import RUOLI, ParametriLega
from ..servizio import Servizio
from . import formato, regole
from .rete import RichiestaOstinata

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s", level=logging.INFO
)
log = logging.getLogger("fantabot")

CHIAVE_SERVIZIO = "servizio"

# Ogni quante ore il bot rilegge le fonti da solo. Sei: gli infortunati
# cambiano piu' volte al giorno vicino alla giornata, e le pagine sono quattro
# richieste in tutto — non c'e' niente da risparmiare andando piu' piano.
ORE_FRA_GLI_AGGIORNAMENTI = 6


def servizio(context: ContextTypes.DEFAULT_TYPE) -> Servizio:
    return context.application.bot_data[CHIAVE_SERVIZIO]


async def _rispondi(update: Update, testo: str, **kwargs) -> None:
    if update.message is not None:
        await update.message.reply_text(testo, parse_mode=ParseMode.HTML, **kwargs)
    elif update.callback_query is not None:
        await update.callback_query.message.reply_text(
            testo, parse_mode=ParseMode.HTML, **kwargs
        )


def _autorizzato(update: Update) -> bool:
    utente = update.effective_user
    return utente is not None and impostazioni().utente_ammesso(utente.id)


async def _lega_o_avviso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """La lega di questa chat, oppure il messaggio che dice come crearla."""
    srv = servizio(context)
    lega = srv.lega(update.effective_chat.id)
    if lega is None:
        await _rispondi(
            update,
            "Prima dimmi com'e' fatta la tua lega:\n\n"
            "<code>/setup 500 8 3-8-8-6</code>\n\n"
            "cioe' crediti, numero di squadre, e slot per portieri, difensori, "
            "centrocampisti e attaccanti.",
        )
        return None
    return lega


# -- comandi di configurazione -------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _autorizzato(update):
        await _rispondi(update, "Questo bot non e' per te.")
        return
    srv = servizio(context)
    quanti = srv.conta_giocatori()
    testo = formato.aiuto()
    if quanti == 0:
        testo += "\n<b>Il listone e' vuoto: lancia /aggiorna prima di cominciare.</b>"
    else:
        testo += f"\n<i>{quanti} giocatori in listone.</i>"
    await _rispondi(update, testo)


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Le regole della lega, scritte come vengono.

    Accetta sia la forma secca <code>/setup 500 8 3-8-8-6</code> sia una frase
    (<code>/setup 10 squadre, 750 crediti, con modificatore</code>), e cambia
    solo quello che nomini: le regole di una lega si decidono spesso dieci
    minuti prima dell'asta, e correggere un dettaglio non deve costare la
    riscrittura di tutto.
    """
    srv = servizio(context)
    detto = regole.leggi(" ".join(context.args or []))
    esistente = srv.lega(update.effective_chat.id)

    if detto.vuote and esistente is None:
        await _rispondi(
            update,
            "Dimmi com'e' fatta la lega, come viene:\n\n"
            "<code>/setup 500 crediti 8 squadre 3-8-8-6</code>\n"
            "<code>/setup 10 squadre, 750 crediti, con modificatore</code>\n\n"
            "<i>Quello che non dici resta com'e'.</i>",
        )
        return
    if detto.vuote:
        await _rispondi(update, regole.descrivi(
                esistente.parametri, esistente.prudenza, esistente.prima_giornata
            ))
        return

    # Quello che non e' stato nominato resta com'era: cosi' "/setup con
    # modificatore" a meta' configurazione non azzera crediti e rose.
    vecchi = esistente.parametri if esistente else ParametriLega()
    crediti = detto.crediti if detto.crediti is not None else vecchi.crediti
    squadre = detto.n_squadre if detto.n_squadre is not None else vecchi.n_squadre
    slot = detto.slot if detto.slot is not None else dict(vecchi.slot)
    modificatore = (
        detto.modificatore_difesa
        if detto.modificatore_difesa is not None
        else vecchi.modificatore_difesa
    )
    buste = (
        detto.offerte_segrete
        if detto.offerte_segrete is not None
        else vecchi.offerte_segrete
    )

    if crediti < 50 or not 2 <= squadre <= 20 or any(n < 1 for n in slot.values()):
        await _rispondi(update, "Quei numeri non stanno in piedi: ricontrolla.")
        return

    srv.crea_lega(
        update.effective_chat.id,
        crediti=crediti,
        n_squadre=squadre,
        slot=slot,
        modificatore_difesa=modificatore,
        offerte_segrete=buste,
    )
    lega = srv.lega(update.effective_chat.id)
    # La giornata di partenza non azzera niente e non c'entra con i
    # prezzi: si applica dopo, sulla lega gia' creata.
    prima = detto.prima_giornata or (esistente.prima_giornata if esistente else 1)
    if prima != lega.prima_giornata:
        srv.imposta_prima_giornata(lega, prima)
        lega = srv.lega(update.effective_chat.id)
    avviso = (
        "\n\n<i>Gli acquisti registrati prima sono stati cancellati: con regole "
        "diverse i prezzi non sarebbero piu' confrontabili.</i>"
        if esistente is not None
        else "\n\n<i>Se vuoi, dai un nome agli avversari:</i>\n"
        "<code>/squadre Marco, Luca, Giulia</code>"
    )
    await _rispondi(
        update,
        regole.descrivi(lega.parametri, lega.prudenza, lega.prima_giornata)
        + avviso,
    )


async def cmd_regole(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rileggere le regole capite dal bot, prima che cominci l'asta."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    await _rispondi(
        update,
        regole.descrivi(lega.parametri, lega.prudenza, lega.prima_giornata),
    )


async def cmd_squadre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    testo = " ".join(context.args or [])
    if not testo.strip():
        squadre = srv.squadre(lega)
        elenco = "\n".join(
            f"<code>{'*' if s.e_mia else ' '} {s.nome}</code>" for s in squadre
        )
        await _rispondi(
            update,
            f"<b>Squadre della lega</b>\n{elenco}\n\n"
            "<i>Per rinominarle: /squadre Marco, Luca, Giulia</i>",
        )
        return
    # "/squadre mia CarmySpecial": la tua, non gli avversari. Sta qui e non in
    # un comando a parte perche' e' la stessa domanda — come si chiamano le
    # squadre — e all'asta un comando in meno da ricordare vale piu' di una
    # separazione elegante.
    pezzi = testo.split(maxsplit=1)
    if len(pezzi) == 2 and pezzi[0].lower() in ("mia", "io", "mio"):
        prima = srv.rinomina_mia(lega, pezzi[1])
        await _rispondi(
            update,
            f"La tua squadra adesso si chiama <b>{pezzi[1].strip()}</b>"
            + (f" <i>(era «{prima}»)</i>." if prima else "."),
        )
        return

    nomi = [n.strip() for n in testo.split(",") if n.strip()]
    esito = srv.rinomina_squadre(lega, nomi)
    mia = next((s.nome for s in srv.squadre(lega) if s.e_mia), "")
    await _rispondi(update, formato.squadre_rinominate(esito, mia))


async def cmd_prudenza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    if not context.args:
        await _rispondi(
            update,
            f"Prudenza attuale: <b>{lega.prudenza:.2f}</b>\n"
            "<i>1.0 = offerte normali · 1.3 = piu' caute · 0.8 = piu' aggressive</i>",
        )
        return
    try:
        valore = float(context.args[0].replace(",", "."))
    except ValueError:
        await _rispondi(update, "Serve un numero, per esempio <code>/prudenza 1.2</code>")
        return
    valore = min(max(valore, 0.6), 2.0)
    srv.imposta_prudenza(lega, valore)
    await _rispondi(update, f"Prudenza impostata a <b>{valore:.2f}</b>.")


def riassunto_aggiornamento(esito: dict) -> str:
    """Cosa e' entrato, in una risposta sola per tutte le fonti."""
    testo = (
        f"<b>Fatto.</b> {esito.get('giocatori', 0)} giocatori, "
        f"{esito.get('statistiche', 0)} righe di statistiche."
    )
    if esito.get("giornate"):
        testo += (
            f"\n<b>{esito['giornate']}ª giornata:</b> minuti letti per "
            f"{esito.get('agganciati', 0)} giocatori, "
            f"{esito.get('previsti', 0)} previsti titolari."
        )
    else:
        testo += (
            "\n<i>Minuti giocati non disponibili: il bot lavora sul listone "
            "e sullo storico, senza sapere chi sta giocando.</i>"
        )
    if esito.get("fermi"):
        testo += (
            f"\n<b>{esito['fermi']} infortunati</b>, di cui "
            f"{esito.get('lunghi', 0)} fermi a lungo. /infortunati per l'elenco."
        )
    return testo


CHIAVE_LEGGE_DA_SOLO = "legge_da_solo"


async def cmd_aggiorna(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rilegge le fonti — o spiega perche' da qui non si puo'.

    Dove il bot gira dietro un proxy che lascia uscire solo verso Telegram, le
    fonti le legge qualcun altro e le manda gia' pronte. Provarci lo stesso
    finirebbe in un timeout e in un messaggio d'errore che sembra un guasto,
    mentre e' il funzionamento normale: meglio dire dove sono i dati e di
    quando sono.
    """
    srv = servizio(context)
    if not context.application.bot_data.get(CHIAVE_LEGGE_DA_SOLO, True):
        await _rispondi(update, formato.dati_da_fuori(srv.quando_sono_arrivati()))
        return
    await _rispondi(update, "Rileggo listone, statistiche, campo e infermeria…")
    try:
        esito = await asyncio.to_thread(aggiorna_tutto, srv.conn)
    except Exception as errore:  # la rete puo' sempre andare male
        log.exception("aggiornamento fallito")
        await _rispondi(
            update,
            f"Non ce l'ho fatta: <code>{errore}</code>\n"
            "<i>Se hai gia' scaricato il listone almeno una volta, "
            "il bot continua a lavorare su quello.</i>",
        )
        return
    srv.invalida_cache()
    await _rispondi(update, riassunto_aggiornamento(esito))


async def rinfresca(context: ContextTypes.DEFAULT_TYPE) -> None:
    """L'aggiornamento che si fa da solo, ogni tot ore.

    PERCHE' NON BASTA `/aggiorna`. Infortuni e formazioni previste cambiano
    ogni giorno, e cambiano soprattutto il venerdi' e il sabato — cioe' quando
    si schiera. Un bot che sa le cose solo quando gliele si chiede e' un bot
    che sa le cose vecchie proprio nel momento in cui contano.

    Gira in un thread perche' le fonti sono sincrone, e se fallisce non dice
    niente a nessuno: un errore di rete alle quattro del mattino non e' una
    notizia, e la prossima passata riprova.
    """
    srv = context.application.bot_data.get(CHIAVE_SERVIZIO)
    if srv is None:
        return
    try:
        esito = await asyncio.to_thread(aggiorna_tutto, srv.conn)
    except Exception:
        log.exception("aggiornamento automatico fallito")
        return
    srv.invalida_cache()
    log.info(
        "aggiornamento automatico: giornata %s, %s infortunati",
        esito.get("giornate", 0),
        esito.get("fermi", 0),
    )



async def cmd_formazione(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chi schierare domenica, con il modulo che rende di piu'."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    stato = srv.stato(lega)
    mia = stato.mia
    if mia is None:
        await _rispondi(update, "Non trovo la tua squadra.")
        return
    # La giornata la puoi dire tu — «/formazione 7» — se vuoi guardare avanti
    # per decidere uno scambio. Senza, e' la prima non ancora giocata.
    args = context.args or []
    giornata = int(args[0]) if args and args[0].isdigit() else srv.giornata_di_oggi(lega)
    consiglio = fmz.consiglia(
        stato, mia, srv.forma_recente(), srv.avversari(stato, giornata)
    )
    await _rispondi(update, formato.formazione(consiglio, giornata))


async def cmd_giornata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Il calendario di una giornata, con dentro chi e' tuo."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    args = context.args or []
    giornata = int(args[0]) if args and args[0].isdigit() else srv.giornata_di_oggi(lega)
    stato = srv.stato(lega)
    await _rispondi(
        update,
        formato.calendario(
            calendario.partite_di(srv.conn, giornata),
            giornata,
            srv.avversari(stato, giornata),
            stato,
            lega.prima_giornata,
        ),
    )


async def cmd_scambi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gli scambi uno-a-uno che convengono a me e anche all'altro."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    mia = stato.mia
    if mia is None:
        await _rispondi(update, "Non trovo la tua squadra.")
        return
    await _rispondi(update, formato.scambi(fmz.scambi_possibili(stato, mia)))


async def cmd_scambio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra un passaggio di proprieta': <code>/scambio vlahovic marco</code>."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    args = list(context.args or [])
    if len(args) < 2:
        await _rispondi(
            update,
            "Dimmi chi va a chi:\n\n"
            "<code>/scambio vlahovic marco</code>\n"
            "<code>/scambio vlahovic io</code>\n"
            "<code>/scambio vlahovic svincolato</code>\n\n"
            "<i>Uno scambio non tocca i crediti: il prezzo pagato all'asta "
            "resta quello, perche' e' quello che il budget l'ha consumato.</i>",
        )
        return
    destinatario = args[-1].lower()
    trovati = cerca(srv.conn, " ".join(args[:-1]))
    if not trovati:
        await _rispondi(update, "Non trovo questo giocatore.")
        return
    stato = srv.stato(lega)
    if destinatario in ("svincolato", "svincola", "fuori", "nessuno"):
        id_squadra = None
        dove = "svincolato"
    else:
        squadra = next(
            (
                s
                for s in stato.squadre
                if destinatario in s.nome.lower()
                or (destinatario in ("io", "me", "mia") and s.e_mia)
            ),
            None,
        )
        if squadra is None:
            await _rispondi(update, f"Non trovo la squadra <b>{args[-1]}</b>.")
            return
        id_squadra, dove = squadra.id, squadra.nome
    errore = srv.sposta(lega, trovati[0]["id_fc"], id_squadra)
    if errore:
        await _rispondi(update, errore)
        return
    srv.invalida_cache()
    await _rispondi(
        update, f"<b>{trovati[0]['nome']}</b> ora e' di <b>{dove}</b>."
    )


async def cmd_andamento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Giornata per giornata di un giocatore: bonus, malus, minuti."""
    srv = servizio(context)
    trovati = cerca(srv.conn, " ".join(context.args or []))
    if not trovati:
        await _rispondi(update, "Dimmi di chi: <code>/andamento malen</code>")
        return
    id_fc = trovati[0]["id_fc"]
    await _rispondi(
        update,
        formato.andamento_giocatore(
            trovati[0]["nome"], andamento.turni(srv.conn, id_fc)
        ),
    )


async def cmd_coppie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gli abbinamenti di calendario: /coppie p, oppure /coppie p con napoli."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    args = [a.lower() for a in (context.args or [])]
    ruolo = _ruolo_da_args(context.args) or "p"
    tabella = coppie.leggi(srv.conn, ruolo)
    stato = srv.stato(lega)

    # "con <nome>" fissa un lato della coppia sul giocatore nominato; senza,
    # si parte da quelli che hai gia' in rosa, che e' la domanda vera a meta'
    # asta — non "qual e' la coppia migliore" ma "come completo la mia".
    partendo_da = None
    if "con" in args:
        trovati = cerca(srv.conn, " ".join(args[args.index("con") + 1 :]))
        if trovati:
            partendo_da = stato.valutazioni.get(trovati[0]["id_fc"])
    elif stato.mia is not None:
        miei = [
            stato.valutazioni[a.id_fc]
            for a in stato.mia.acquisti
            if a.ruolo == ruolo and a.id_fc in stato.valutazioni
        ]
        if miei and stato.slot_mancanti(stato.mia).get(ruolo, 0) > 0:
            partendo_da = max(miei, key=lambda v: v.valore)

    blocchi = []
    for fasce in fmz.FASCE_ABBINABILI.get(ruolo, (None,)):
        if partendo_da is not None and fasce is not None:
            if fmz.fascia_di(partendo_da) not in fasce:
                continue
        elenco = fmz.abbinamenti(
            stato, tabella, ruolo, limite=6, partendo_da=partendo_da, fasce=fasce
        )
        blocchi.append(
            formato.abbinamenti(
                elenco,
                ruolo,
                partendo_da,
                fasce=fasce,
            )
        )
    await _rispondi(update, "\n\n".join(blocchi))


async def cmd_infortunati(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    await _rispondi(update, formato.infortunati(servizio(context).stato(lega)))


async def cmd_squalificati(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chi salta la prossima, e chi rischia quella dopo."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    stato = srv.stato(lega)
    await _rispondi(update, formato.squalificati(stato))


async def cmd_turno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Di chi e' la chiamata. Senza argomenti dice chi tocca; con un nome, lo imposta."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    stato = srv.stato(lega)
    detto = " ".join(context.args or []).strip()
    if detto:
        cercato = detto.lower()
        trovata = next(
            (
                i
                for i, s in enumerate(stato.squadre)
                if cercato in s.nome.lower() or (cercato in ("io", "me") and s.e_mia)
            ),
            None,
        )
        if trovata is None:
            await _rispondi(update, f"Non trovo la squadra <b>{detto}</b>.")
            return
        srv.imposta_turno(lega, trovata)
        lega = srv.lega(update.effective_chat.id)
    await _rispondi(update, formato.turno(stato, lega.turno, lega.reparto))


async def cmd_reparto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Il reparto in asta adesso, per le leghe che chiamano a reparti."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    detto = " ".join(context.args or []).strip().lower()
    if detto in ("libero", "libera", "no", "-"):
        srv.imposta_reparto(lega, "")
        await _rispondi(update, "<b>Chiamata libera:</b> ogni reparto e' aperto.")
        return
    ruolo = _ruolo_da_args(context.args)
    if ruolo is None:
        attuale = (
            formato.PLURALE_RUOLO[lega.reparto].lower() if lega.reparto else "tutti"
        )
        await _rispondi(
            update,
            f"Reparto in asta adesso: <b>{attuale}</b>.\n\n"
            "<code>/reparto p</code> per aprire i portieri, "
            "<code>/reparto libero</code> per togliere il vincolo.",
        )
        return
    srv.imposta_reparto(lega, ruolo)
    lega = srv.lega(update.effective_chat.id)
    await _rispondi(update, formato.turno(srv.stato(lega), lega.turno, lega.reparto))


async def cmd_campo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chi gioca e chi no, fra i giocatori che ti interessano."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    ruolo = _ruolo_da_args(context.args)
    await _rispondi(update, formato.campo_squadra(stato, ruolo))


# -- durante l'asta -------------------------------------------------------


async def cmd_rosa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    filtro = " ".join(context.args or []).strip().lower()
    if filtro:
        squadra = next(
            (s for s in stato.squadre if filtro in s.nome.lower()), None
        )
        if squadra is None:
            await _rispondi(update, "Non trovo quella squadra.")
            return
    else:
        squadra = stato.mia
    await _rispondi(update, formato.rosa(stato, squadra))


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    await _rispondi(update, formato.budget(servizio(context).stato(lega)))


async def cmd_mercato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    await _rispondi(update, formato.mercato(servizio(context).stato(lega)))


def _ruolo_da_args(args: list[str] | None) -> str | None:
    if not args:
        return None
    testo = args[0].strip().lower()
    per_iniziale = {"p": "p", "d": "d", "c": "c", "a": "a"}
    return per_iniziale.get(testo[0]) if testo else None


async def cmd_liberi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    ruolo = _ruolo_da_args(context.args)
    correnti = stato.prezzi_correnti()
    liberi = [v for v in stato.disponibili() if not ruolo or v.giocatore.ruolo == ruolo]
    liberi.sort(key=lambda v: -correnti.get(v.giocatore.id_fc, 1.0))
    voci = []
    for v in liberi[:15]:
        c = stato.consiglia(v.giocatore.id_fc, lega.prudenza)
        voci.append(
            (v, correnti.get(v.giocatore.id_fc, 1.0), c.massimo if c else 0)
        )
    titolo = (
        f"I migliori {formato.PLURALE_RUOLO[ruolo].lower()} liberi"
        if ruolo
        else "I piu' costosi ancora liberi"
    )
    await _rispondi(update, formato.elenco(titolo, voci))


async def cmd_occasioni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    ruolo = _ruolo_da_args(context.args)
    consigli = stato.occasioni(ruolo=ruolo, limite=12)
    voci = [(c.valutazione, c.prezzo_corrente, c.massimo) for c in consigli]
    titolo = "Rendono piu' di quanto costano"
    if ruolo:
        titolo += f" — {formato.PLURALE_RUOLO[ruolo].lower()}"
    testo = formato.elenco(titolo, voci)
    if voci:
        testo += "\n<i>Ordinati per crediti di valore guadagnati, non per fama.</i>"
    await _rispondi(update, testo)


async def cmd_chiama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    scelte = stato.da_chiamare(limite=6)
    await _rispondi(
        update,
        formato.consigli(
            "Chiamali adesso",
            scelte,
            "Sono i giocatori che ti convengono e che pochi possono contenderti "
            "in questo momento. Chiamare e' una mossa: il momento giusto e' "
            "quando chi li vuole ha gia' speso.",
        ),
    )


async def documento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Un foglio mandato in chat: prezzi d'asta veri da un altro tool.

    E' il dato che questo bot puo' solo stimare - a quanto un giocatore viene
    pagato davvero, misurato su migliaia di aste. Quando arriva, il numero
    osservato prende il posto della stima, e al motore resta il mestiere che
    il foglio non fa: dire quanto vale per te, chi te lo puo' contendere e
    quanto ti rimane in tasca.
    """
    if not _autorizzato(update):
        return
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    documento_ricevuto = update.message.document
    nome_file = documento_ricevuto.file_name or "listino.xlsx"
    if not nome_file.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt")):
        await _rispondi(
            update,
            "Mi servono un Excel o un CSV. "
            "<i>Da FantaLab: Strategia → Esporta in Excel.</i>",
        )
        return

    await _rispondi(update, f"Leggo <b>{nome_file}</b>…")
    file_telegram = await documento_ricevuto.get_file()
    dati = bytes(await file_telegram.download_as_bytearray())
    esito = await asyncio.to_thread(importa, srv.conn, dati, nome_file)
    srv.invalida_cache()
    await _rispondi(update, formato.esito_import(esito))
    # Un foglio nuovo puo' aver tolto qualcuno dal giro: e' il momento in cui
    # dirlo, non tre giorni dopo quando ti accorgi che un nome non esce piu'.
    esclusi = srv.fuori_lista()
    if esclusi:
        await _rispondi(
            update, formato.fuori_lista(esclusi, srv.conta_giocatori())
        )


async def cmd_importa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Spiega come si importa, e dice cosa c'e' gia' dentro."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    await _rispondi(update, formato.stato_import(riassunto(srv.conn)))


async def cmd_azzera(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancella le rose e lascia in piedi regole, nomi e foglio delle fasce.

    CHIEDE PRIMA, e chiede mostrando i numeri. Fino a ieri l'unico modo di
    ripulire era rifare /setup, che cancellava gli acquisti come effetto
    collaterale di un comando che serve ad altro: il tipo di scorciatoia che
    prima o poi ti porta via una rosa vera credendo di cambiare i crediti.
    """
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    perso = srv.cosa_si_perde(lega)
    if not perso["acquisti"] and not perso["preferenze"]:
        await _rispondi(update, formato.conferma_azzera(perso))
        return
    bottoni = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Sì, azzera l'asta", callback_data="z:si")],
            [InlineKeyboardButton("No, lascia stare", callback_data="z:no")],
        ]
    )
    await _rispondi(
        update, formato.conferma_azzera(perso, lega.nome), reply_markup=bottoni
    )


async def cmd_fuorilista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chi c'e' nel listone ma non nelle fasce: non lo consiglio piu'."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    await _rispondi(
        update, formato.fuori_lista(srv.fuori_lista(), srv.conta_giocatori())
    )


async def cmd_piano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manda il foglio d'asta come file: si stampa e sopravvive al telefono."""
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    stato = srv.stato(lega)
    testo = formato.piano_testo(stato, srv.preferenze(lega))
    documento = BytesIO(testo.encode("utf-8"))
    documento.name = "piano-asta.txt"
    destinatario = update.message or update.callback_query.message
    await destinatario.reply_document(
        document=documento,
        filename="piano-asta.txt",
        caption=(
            "Il foglio completo, reparto per reparto. Si aggiorna a ogni "
            "chiamata: rilancialo quando l'asta e' entrata nel vivo."
        ),
    )


async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    stato = srv.stato(lega)
    voci = []
    for id_fc, grado in srv.preferenze(lega).items():
        v = stato.valutazioni.get(id_fc)
        if v is None or grado == 0:
            continue
        preso = stato.presi.get(id_fc)
        serve = stato.serve_per_vincere(id_fc) if preso is None else 0
        voci.append((v, grado, preso.nome if preso else "", serve))
    voci.sort(key=lambda t: (-t[1], t[0].giocatore.ruolo))
    await _rispondi(update, formato.lista_obiettivi(stato, voci))


async def _imposta_preferenza(
    update: Update, context: ContextTypes.DEFAULT_TYPE, grado: int
) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    nome = " ".join(context.args or []).strip()
    if not nome:
        await _rispondi(
            update,
            "Serve un nome: <code>/target vlahovic</code>. "
            "Oppure usa i bottoni sotto la scheda del giocatore.",
        )
        return
    trovati = cerca(srv.conn, nome)
    if not trovati:
        await _rispondi(update, f"Non trovo nessuno che somigli a <b>{nome}</b>.")
        return
    srv.imposta_preferenza(lega, trovati[0]["id_fc"], grado)
    verbo = "un obiettivo" if grado > 0 else "da evitare"
    await _rispondi(update, f"<b>{trovati[0]['nome']}</b> è ora {verbo}.")


async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _imposta_preferenza(update, context, 1)


async def cmd_evita(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _imposta_preferenza(update, context, -1)


async def cmd_riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    stato = servizio(context).stato(lega)
    filtro = " ".join(context.args or []).strip().lower()
    squadra = (
        next((s for s in stato.squadre if filtro in s.nome.lower()), None)
        if filtro
        else stato.mia
    )
    if squadra is None:
        await _rispondi(update, "Non trovo quella squadra.")
        return
    await _rispondi(update, formato.riepilogo(stato, squadra))


async def cmd_correggi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    args = context.args or []
    if len(args) < 2 or not args[-1].isdigit():
        await _rispondi(
            update, "Si scrive <code>/correggi vlahovic 32</code>."
        )
        return
    trovati = cerca(srv.conn, " ".join(args[:-1]))
    if not trovati:
        await _rispondi(update, "Non trovo quel giocatore.")
        return
    errore = srv.correggi_prezzo(lega, trovati[0]["id_fc"], int(args[-1]))
    if errore:
        await _rispondi(update, errore)
        return
    await _rispondi(
        update, f"<b>{trovati[0]['nome']}</b> ora risulta pagato {args[-1]}."
    )


async def cmd_annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    nome = " ".join(context.args or []).strip()
    if nome:
        trovati = cerca(srv.conn, nome)
        if not trovati:
            await _rispondi(update, f"Non trovo nessuno che somigli a <b>{nome}</b>.")
            return
        tolto = srv.annulla_giocatore(lega, trovati[0]["id_fc"])
        if tolto is None:
            await _rispondi(
                update, f"<b>{trovati[0]['nome']}</b> non risulta assegnato a nessuno."
            )
            return
        await _rispondi(update, f"Annullato: <b>{tolto}</b>")
        return
    tolto = srv.annulla_ultimo(lega)
    if tolto is None:
        await _rispondi(update, "Non c'e' niente da annullare.")
    else:
        await _rispondi(update, f"Annullato: <b>{tolto}</b>")


# -- il messaggio libero: il modo veloce ----------------------------------


@dataclass(frozen=True)
class Comando:
    nome: str
    prezzo: int | None = None
    mio: bool = False
    squadra: str = ""


def _spezza(testo: str) -> Comando:
    """Legge le tre forme in cui si scrive in asta.

    <code>vlahovic</code>, <code>+vlahovic 25</code>, e la piu' veloce di
    tutte, <code>vlahovic 25 marco</code>, che assegna senza nemmeno il tap
    sul bottone. Il numero fa da separatore: prima c'e' il giocatore, dopo la
    squadra. Registrare in fretta non e' comodita' - se non registri quello
    che comprano gli altri, il bot crede che abbiano ancora tutti i crediti e
    ti consiglia offerte troppo basse.
    """
    testo = testo.strip()
    mio = testo.startswith("+")
    pezzi = testo.lstrip("+").strip().split()
    indice = next((i for i, p in enumerate(pezzi) if p.isdigit()), None)
    if indice is None or indice == 0:
        return Comando(nome=" ".join(pezzi), mio=mio)
    return Comando(
        nome=" ".join(pezzi[:indice]),
        prezzo=int(pezzi[indice]),
        mio=mio,
        squadra=" ".join(pezzi[indice + 1 :]),
    )


async def messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _autorizzato(update):
        return
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    srv = servizio(context)
    cmd = _spezza(update.message.text or "")
    if not cmd.nome:
        return

    trovati = cerca(srv.conn, cmd.nome)
    if not trovati:
        await _rispondi(update, f"Non trovo nessuno che somigli a <b>{cmd.nome}</b>.")
        return

    if len(trovati) > 1 and trovati[0]["nome_cerca"] != cmd.nome.lower():
        bottoni = [
            [
                InlineKeyboardButton(
                    f"{r['nome']} ({r['squadra']} {r['ruolo'].upper()})",
                    callback_data=(
                        f"g:{r['id_fc']}:{cmd.prezzo or ''}:{int(cmd.mio)}"
                    ),
                )
            ]
            for r in trovati[:6]
        ]
        await _rispondi(update, "Quale?", reply_markup=InlineKeyboardMarkup(bottoni))
        return

    id_fc = trovati[0]["id_fc"]

    # "lautaro 94 marco": la squadra e' gia' nel messaggio, niente tap.
    if cmd.prezzo is not None and cmd.squadra and not cmd.mio:
        stato = srv.stato(lega)
        chiave = cmd.squadra.strip().lower()
        candidate = [s for s in stato.squadre if s.nome.lower().startswith(chiave)]
        if not candidate and chiave.isdigit():
            # "lautaro 25 3" = la terza squadra dell'elenco. Con gli avversari
            # ancora chiamati "Avversario 1..7" scrivere il numero e' piu'
            # veloce, e all'asta la velocita' e' correttezza.
            indice = int(chiave)
            if 1 <= indice <= len(stato.squadre):
                candidate = [stato.squadre[indice - 1]]
        if len(candidate) == 1:
            await _registra(update, context, lega, id_fc, candidate[0].id, cmd.prezzo)
            return
        if not candidate:
            await _rispondi(
                update,
                f"Non ho una squadra che cominci per <b>{cmd.squadra}</b>. "
                "Scegli qui sotto.",
            )

    await _agisci(update, context, lega, id_fc, cmd.prezzo, cmd.mio)


def _nome_dal_listone(srv: Servizio, id_fc: int) -> str:
    """Il nome di un giocatore che il motore non sa valutare, per poterlo dire."""
    r = srv.conn.execute(
        "SELECT nome FROM giocatori WHERE id_fc = ?", (id_fc,)
    ).fetchone()
    return r["nome"] if r else "Giocatore sconosciuto"


def _bottoni_scheda(id_fc: int, preferenza: int) -> InlineKeyboardMarkup:
    """Obiettivo o da evitare, con un tap invece che con un comando.

    All'asta si digita male e in fretta: ogni cosa che si puo' fare con un
    pollice va fatta con un pollice.
    """
    if preferenza > 0:
        voluto = InlineKeyboardButton("◎ togli obiettivo", callback_data=f"p:{id_fc}:0")
    else:
        voluto = InlineKeyboardButton("◎ obiettivo", callback_data=f"p:{id_fc}:1")
    if preferenza < 0:
        evitato = InlineKeyboardButton("✕ non evitarlo", callback_data=f"p:{id_fc}:0")
    else:
        evitato = InlineKeyboardButton("✕ evita", callback_data=f"p:{id_fc}:-1")
    return InlineKeyboardMarkup([[voluto, evitato]])


async def _agisci(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lega,
    id_fc: int,
    prezzo: int | None,
    mio: bool,
) -> None:
    """Con un prezzo si registra, senza si consiglia."""
    srv = servizio(context)
    if prezzo is None:
        stato = srv.stato(lega)
        c = stato.consiglia(id_fc, lega.prudenza)
        if c is None:
            await _rispondi(
                update,
                f"<b>{_nome_dal_listone(srv, id_fc)}</b> e' nel listone ma senza "
                "ruolo assegnato: non riesco a valutarlo. "
                "<i>Succede con gli acquisti dell'ultima ora; riprova dopo "
                "/aggiorna.</i>",
            )
            return
        preso_da = stato.presi.get(id_fc)
        if preso_da is not None:
            await _rispondi(
                update,
                f"<b>{c.valutazione.giocatore.nome}</b> e' gia' di "
                f"<b>{preso_da.nome}</b>.",
            )
            return
        testo = formato.scheda(c, stato)
        if mio:
            # "+vlahovic" senza cifra: voleva registrarlo, non consultarlo.
            testo += (
                f"\n\n<i>Per registrarlo scrivi "
                f"<code>+{c.valutazione.giocatore.nome.lower()} 25</code>, "
                "con quanto lo hai pagato.</i>"
            )
        await _rispondi(
            update, testo, reply_markup=_bottoni_scheda(id_fc, c.preferenza)
        )
        return

    if mio:
        stato = srv.stato(lega)
        mia = stato.mia
        await _registra(update, context, lega, id_fc, mia.id, prezzo)
        return

    stato = srv.stato(lega)
    v = stato.valutazioni.get(id_fc)
    nome = v.giocatore.nome if v else _nome_dal_listone(srv, id_fc)
    bottoni = [
        [
            InlineKeyboardButton(
                ("★ " if s.e_mia else "") + s.nome,
                callback_data=f"a:{id_fc}:{prezzo}:{s.id}",
            )
        ]
        for s in stato.squadre
    ]
    await _rispondi(
        update,
        f"<b>{nome}</b> a {prezzo}. Chi se l'e' preso?",
        reply_markup=InlineKeyboardMarkup(bottoni),
    )


async def _registra(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lega,
    id_fc: int,
    id_squadra: int,
    prezzo: int,
) -> None:
    srv = servizio(context)
    errore = srv.registra(lega, id_fc, id_squadra, prezzo)
    if errore:
        await _rispondi(update, errore)
        return
    stato = srv.stato(lega)
    squadra = next((s for s in stato.squadre if s.id == id_squadra), None)
    v = stato.valutazioni.get(id_fc)
    nome = v.giocatore.nome if v else _nome_dal_listone(srv, id_fc)
    testo = [f"<b>{nome}</b> → {squadra.nome} per {prezzo}"]
    if squadra.e_mia:
        mancanti = stato.slot_mancanti(squadra)
        testo.append(
            f"<code>ti restano {stato.crediti_residui(squadra)} crediti · "
            f"{stato.slot_mancanti_totali(squadra)} slot ("
            + " ".join(
                f"{formato.SIMBOLO_RUOLO[r]}{mancanti[r]}" for r in RUOLI if mancanti[r]
            )
            + ")</code>"
        )
        piano = stato.piano_spesa()
        testo.append(
            "<i>da qui: "
            + " · ".join(
                f"{formato.SIMBOLO_RUOLO[r]} {piano[r]}"
                for r in RUOLI
                if mancanti[r] > 0
            )
            + "</i>"
        )
    else:
        infl = stato.inflazione()
        if infl >= 1.15 or infl <= 0.9:
            testo.append(formato._frase_inflazione(infl))
    if squadra.e_mia and v is not None:
        completa = _come_completare(srv, stato, v)
        if completa:
            testo.append(completa)
    avviso = _avvisi_obiettivi(stato, srv.preferenze(lega))
    if avviso:
        testo.append(avviso)
    await _rispondi(update, "\n".join(testo))


def _come_completare(srv: Servizio, stato, comprato) -> str:
    """Con chi si abbina bene quello che ho appena preso.

    ARRIVA DA SOLO, subito dopo l'acquisto, e non e' una comodita': il momento
    in cui hai appena comprato un portiere e' l'unico in cui la domanda "e
    adesso il secondo?" ha ancora tutte le risposte disponibili. Farla
    mezz'ora dopo vuol dire farla quando i tre nomi buoni sono andati.

    In attacco la coppia rispetta le fasce — un Top si completa con un
    Semi-Top, una Terza con una Quarta — perche' e' cosi' che si compone un
    reparto: due Top costano mezzo budget e due Quarte non fanno una domenica.
    """
    ruolo = comprato.giocatore.ruolo
    tabella = coppie.leggi(srv.conn, ruolo)
    if not tabella or stato.mia is None:
        return ""
    if stato.slot_mancanti(stato.mia).get(ruolo, 0) <= 0:
        return ""
    fasce = next(
        (
            possibili
            for possibili in fmz.FASCE_ABBINABILI.get(ruolo, ())
            if fmz.fascia_di(comprato) in possibili
        ),
        None,
    )
    trovati = fmz.abbinamenti(
        stato, tabella, ruolo, limite=3, partendo_da=comprato, fasce=fasce
    )
    if not trovati:
        return ""
    righe = ["\n<b>Con chi si abbina</b>"]
    for x in trovati:
        altro = (
            x.secondo
            if x.primo.giocatore.id_fc == comprato.giocatore.id_fc
            else x.primo
        )
        righe.append(
            f"<code>{x.punteggio:>3}  {altro.giocatore.nome[:16]:<16} "
            f"{altro.prezzo_mercato:>4.0f}</code>"
        )
    return "\n".join(righe)


def _avvisi_obiettivi(stato, preferenze: dict[int, int]) -> str:
    """Cosa e' cambiato per i tuoi obiettivi dopo quest'ultima assegnazione.

    Il momento in cui un avversario chiude un reparto e' il momento in cui il
    tuo obiettivo diventa economico - e passa inosservato, perche' succede
    mentre stai guardando un altro giocatore. Il bot lo dice da solo, invece
    di aspettare che tu pensi a chiedere.
    """
    righe = []
    for id_fc, grado in preferenze.items():
        if grado <= 0 or id_fc in stato.presi:
            continue
        c = stato.consiglia(id_fc)
        if c is None or c.massimo <= 0:
            continue
        if not c.rivali:
            righe.append(
                f"◎ <b>{c.valutazione.giocatore.nome}</b>: "
                "non te lo puo' piu' togliere nessuno"
            )
        elif len(c.rivali) == 1:
            righe.append(
                f"◎ <b>{c.valutazione.giocatore.nome}</b>: solo "
                f"{c.rivali[0].squadra.nome} puo' contendertelo, basta {c.serve}"
            )
    return "\n" + "\n".join(righe[:3]) if righe else ""


async def bottone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _autorizzato(update):
        return
    query = update.callback_query
    await query.answer()
    lega = await _lega_o_avviso(update, context)
    if lega is None:
        return
    pezzi = (query.data or "").split(":")
    if pezzi[0] == "g":
        id_fc = int(pezzi[1])
        prezzo = int(pezzi[2]) if len(pezzi) > 2 and pezzi[2] else None
        mio = bool(int(pezzi[3])) if len(pezzi) > 3 and pezzi[3] else False
        await _agisci(update, context, lega, id_fc, prezzo, mio)
    elif pezzi[0] == "a":
        await _registra(
            update, context, lega, int(pezzi[1]), int(pezzi[3]), int(pezzi[2])
        )
    elif pezzi[0] == "z":
        if pezzi[1] != "si":
            await _rispondi(update, "Non ho toccato niente.")
            return
        srv = servizio(context)
        perso = srv.azzera_asta(lega)
        await _rispondi(update, formato.azzerata(perso))
    elif pezzi[0] == "p":
        srv = servizio(context)
        id_fc, grado = int(pezzi[1]), int(pezzi[2])
        srv.imposta_preferenza(lega, id_fc, grado)
        stato = srv.stato(lega)
        v = stato.valutazioni.get(id_fc)
        nome = v.giocatore.nome if v else _nome_dal_listone(srv, id_fc)
        testo = {
            1: f"<b>{nome}</b> è un obiettivo: offrirò il 15% in più per averlo.",
            -1: f"<b>{nome}</b> tra quelli da evitare: offrirò meno.",
            0: f"<b>{nome}</b> torna neutro.",
        }[grado]
        await _rispondi(update, testo)


async def errore(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dire cosa e' successo davvero, che non e' sempre «non ha funzionato».

    Un errore di RETE arriva quasi sempre mentre si spedisce la risposta,
    cioe' DOPO che il comando ha fatto il suo lavoro. Chiamarlo «qualcosa e'
    andato storto» invita a riscrivere il comando — e un acquisto registrato
    due volte e' peggio di una conferma non arrivata.
    """
    log.exception("errore non gestito", exc_info=context.error)
    if not (isinstance(update, Update) and update.effective_message):
        return
    if isinstance(context.error, NetworkError):
        testo = (
            "Il collegamento con Telegram e' caduto un attimo mentre "
            "rispondevo.\n<b>Quello che mi hai chiesto potrebbe essere gia' "
            "fatto</b>: controlla con /rosa o /squadre prima di riscriverlo."
        )
    else:
        testo = "Qualcosa e' andato storto. Riprova, e se insiste guarda i log."
    await context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=testo,
        parse_mode=ParseMode.HTML,
    )


def costruisci(
    conn: sqlite3.Connection | None = None, *, aggiorna_da_solo: bool = True
) -> Application:
    """Il bot montato, comandi e lavori periodici.

    `aggiorna_da_solo` si spegne quando le fonti le legge qualcun altro —
    su PythonAnywhere gratis, dove la whitelist non lascia uscire, i dati
    arrivano gia' pronti da GitHub Actions e un lavoro che prova a
    scaricarli da qui riuscirebbe solo a riempire i log di errori.
    """
    cfg = impostazioni()
    if not cfg.token_telegram:
        raise SystemExit(
            "Manca TELEGRAM_BOT_TOKEN. Crea il bot con @BotFather, "
            "copia il token in un file .env accanto a questo progetto:\n"
            "  TELEGRAM_BOT_TOKEN=123456:ABC...\n"
        )
    # Il trasporto che riprova: dove il bot gira dietro un proxy condiviso,
    # un 503 di mezzo secondo non deve diventare un errore in faccia a chi sta
    # facendo l'asta.
    app = (
        Application.builder()
        .token(cfg.token_telegram)
        .request(RichiestaOstinata())
        .get_updates_request(RichiestaOstinata())
        .build()
    )
    servizio_ = Servizio(conn or connetti())
    app.bot_data[CHIAVE_SERVIZIO] = servizio_
    app.bot_data[CHIAVE_LEGGE_DA_SOLO] = aggiorna_da_solo
    # Le matrici di abbinamento che il progetto porta con se', se non ne hai
    # gia' importata una tua.
    coppie.carica_semi(servizio_.conn)
    calendario.carica_seme(servizio_.conn)

    app.add_handler(CommandHandler(["start", "aiuto", "help"], cmd_start))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("regole", cmd_regole))
    app.add_handler(CommandHandler("squadre", cmd_squadre))
    app.add_handler(CommandHandler("prudenza", cmd_prudenza))
    app.add_handler(CommandHandler("aggiorna", cmd_aggiorna))
    app.add_handler(CommandHandler("campo", cmd_campo))
    app.add_handler(CommandHandler("infortunati", cmd_infortunati))
    app.add_handler(CommandHandler(["squalificati", "diffidati"], cmd_squalificati))
    app.add_handler(CommandHandler("coppie", cmd_coppie))
    app.add_handler(CommandHandler("formazione", cmd_formazione))
    app.add_handler(CommandHandler(["giornata", "calendario"], cmd_giornata))
    app.add_handler(CommandHandler("scambi", cmd_scambi))
    app.add_handler(CommandHandler("scambio", cmd_scambio))
    app.add_handler(CommandHandler("andamento", cmd_andamento))
    app.add_handler(CommandHandler("turno", cmd_turno))
    app.add_handler(CommandHandler("reparto", cmd_reparto))
    app.add_handler(CommandHandler("rosa", cmd_rosa))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("mercato", cmd_mercato))
    app.add_handler(CommandHandler("liberi", cmd_liberi))
    app.add_handler(CommandHandler("occasioni", cmd_occasioni))
    app.add_handler(CommandHandler("chiama", cmd_chiama))
    app.add_handler(CommandHandler("piano", cmd_piano))
    app.add_handler(CommandHandler("importa", cmd_importa))
    app.add_handler(CommandHandler(["fuorilista", "fuori"], cmd_fuorilista))
    app.add_handler(CommandHandler(["azzera", "reset"], cmd_azzera))
    app.add_handler(CommandHandler("lista", cmd_lista))
    app.add_handler(CommandHandler("target", cmd_target))
    app.add_handler(CommandHandler("evita", cmd_evita))
    app.add_handler(CommandHandler("riepilogo", cmd_riepilogo))
    app.add_handler(CommandHandler("correggi", cmd_correggi))
    app.add_handler(CommandHandler("annulla", cmd_annulla))
    app.add_handler(MessageHandler(filters.Document.ALL, documento))
    app.add_handler(CallbackQueryHandler(bottone))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messaggio))
    app.add_error_handler(errore)

    # L'AGGIORNAMENTO CHE SI FA DA SOLO. Infortuni e formazioni previste
    # cambiano ogni giorno, e cambiano soprattutto fra il venerdi' e la
    # domenica mattina: un bot che sa le cose solo quando gliele si chiede sa
    # le cose vecchie proprio nel momento in cui contano.
    #
    # Il primo giro parte dopo un minuto e non subito: all'avvio si vuole un
    # bot che risponde, non un bot che sta scaricando.
    if not aggiorna_da_solo:
        log.info("aggiornamento automatico spento: i dati arrivano da fuori")
    elif app.job_queue is not None:
        app.job_queue.run_repeating(
            rinfresca,
            interval=ORE_FRA_GLI_AGGIORNAMENTI * 3600,
            first=60,
            name="rinfresca",
        )
    else:  # pragma: no cover - dipende da come e' installato python-telegram-bot
        log.warning(
            "JobQueue non disponibile: niente aggiornamento automatico. "
            "Installa python-telegram-bot[job-queue]."
        )
    return app


def main() -> None:
    app = costruisci()
    log.info("Fantabot in ascolto.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
