"""Chi non c'e' piu': il listone lo elenca ancora, le fasce no.

Il listone di fantacalcio.it non si aggiorna quando uno cambia campionato — a
mercato chiuso Leao risultava ancora al Milan con il suo FVM da 75, e il bot lo
consigliava. Il file delle fasce e' compilato da chi il mercato lo ha seguito,
quindi la sua assenza vale come smentita.

Il danno non era solo il nome sbagliato in un consiglio: un giocatore che non
esiste entra fra i comprabili, si prende la sua fetta del budget della lega e
rende tutti gli altri piu' economici di quanto siano. Qui si controlla che
sparisca dal mercato **senza** sparire dal bot: se il banditore lo chiama, la
scheda deve ancora uscire e dire perche' non va comprato.
"""

from __future__ import annotations

from dataclasses import replace

from fantabot.dati.magazzino import carica_giocatori, fuori_lista
from fantabot.motore.asta import Squadra, StatoAsta
from fantabot.motore.valutazione import valuta


def _nelle_fasce(conn, ids) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO mercato_esterno (id_fc, fascia) VALUES (?, 1)",
        [(i,) for i in ids],
    )
    conn.commit()


def _tutti_tranne(conn, esclusi: set[int]) -> None:
    ids = [
        r[0]
        for r in conn.execute("SELECT id_fc FROM giocatori")
        if r[0] not in esclusi
    ]
    _nelle_fasce(conn, ids)


# -- quando il filtro si applica, e quando no -----------------------------


def test_senza_fasce_non_si_esclude_nessuno(conn_popolato):
    """Senza il foglio, il listone e' tutto quello che si ha."""
    assert fuori_lista(conn_popolato) == set()
    assert all(g.in_lista for g in carica_giocatori(conn_popolato))


def test_un_import_quasi_vuoto_non_cancella_il_listone(conn_popolato):
    """Trenta nomi su trecento sono un import rotto, non una lista corta.

    E' la sera dell'asta: la risposta giusta a un foglio che non combacia non
    e' togliere il novanta per cento dei giocatori.
    """
    pochi = [r[0] for r in conn_popolato.execute("SELECT id_fc FROM giocatori LIMIT 30")]
    _nelle_fasce(conn_popolato, pochi)
    assert fuori_lista(conn_popolato) == set()


def test_chi_manca_nelle_fasce_e_fuori_lista(conn_popolato):
    _tutti_tranne(conn_popolato, {211, 212})
    assert fuori_lista(conn_popolato) == {211, 212}
    per_id = {g.id_fc: g for g in carica_giocatori(conn_popolato)}
    assert per_id[211].in_lista is False
    assert per_id[213].in_lista is True


def test_una_riga_senza_fascia_vale_comunque(conn_popolato):
    """Nel foglio ci sono anche righe senza fascia: esserci basta.

    Sono giocatori veri di cui il file non dichiara la fascia. Chiedere la
    fascia invece della presenza ne avrebbe cancellati settantasei di colpo.
    """
    _tutti_tranne(conn_popolato, set())
    conn_popolato.execute("UPDATE mercato_esterno SET fascia = NULL WHERE id_fc = 5")
    conn_popolato.commit()
    assert 5 not in fuori_lista(conn_popolato)


# -- cosa cambia nei numeri -----------------------------------------------


def test_chi_e_fuori_lista_non_consuma_crediti(listone, parametri):
    """Il fantasma esce dai comprabili: il suo prezzo torna al minimo."""
    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    con = valuta(listone, parametri)
    senza = valuta(
        [replace(g, in_lista=False) if g is fantasma else g for g in listone],
        parametri,
    )
    assert con[fantasma.id_fc].prezzo_mercato > 10
    assert senza[fantasma.id_fc].prezzo_mercato == 1.0


def test_gli_altri_costano_di_piu_senza_il_fantasma(listone, parametri):
    """I crediti che il fantasma si prendeva tornano agli altri.

    E' il motivo per cui non basta filtrarlo dai consigli: finche' resta nel
    conto, ogni prezzo che il bot dice e' piu' basso del vero.
    """
    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    altro = next(
        g for g in listone if g.ruolo == "a" and g is not fantasma and g.fvm > 100
    )
    con = valuta(listone, parametri)
    senza = valuta(
        [replace(g, in_lista=False) if g is fantasma else g for g in listone],
        parametri,
    )
    assert senza[altro.id_fc].prezzo_mercato > con[altro.id_fc].prezzo_mercato


def test_il_fantasma_resta_valutabile(listone, parametri):
    """La scheda deve uscire lo stesso: se lo chiamano, vuoi saperlo."""
    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    senza = valuta(
        [replace(g, in_lista=False) if g is fantasma else g for g in listone],
        parametri,
    )
    v = senza[fantasma.id_fc]
    assert v.valore > 1.0
    assert v.giocatore.in_lista is False


# -- cosa cambia nell'asta ------------------------------------------------


def _stato(listone, parametri, fuori: set[int], acquisti=()) -> StatoAsta:
    giocatori = [replace(g, in_lista=g.id_fc not in fuori) for g in listone]
    mia = Squadra(id=1, nome="La mia", e_mia=True, acquisti=list(acquisti))
    return StatoAsta(
        parametri, valuta(giocatori, parametri), [mia, Squadra(id=2, nome="Altro")]
    )


def test_i_disponibili_non_lo_contengono(listone, parametri):
    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    stato = _stato(listone, parametri, {fantasma.id_fc})
    assert fantasma.id_fc not in {v.giocatore.id_fc for v in stato.disponibili()}
    assert fantasma.id_fc in stato.valutazioni


def test_in_gioco_tiene_chi_e_gia_stato_comprato(listone, parametri):
    """Se qualcuno l'ha gia' pagato, dalla lega non sparisce.

    Toglierlo cancellerebbe i crediti che ha speso e la rosa non tornerebbe
    piu' — che a meta' asta e' un errore che non si recupera.
    """
    from fantabot.motore.asta import Acquisto

    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    acquisto = Acquisto(
        id_fc=fantasma.id_fc, nome=fantasma.nome, ruolo="a", id_squadra=1, prezzo=30
    )
    stato = _stato(listone, parametri, {fantasma.id_fc}, acquisti=(acquisto,))
    assert fantasma.id_fc in {v.giocatore.id_fc for v in stato.in_gioco()}
    assert fantasma.id_fc not in {v.giocatore.id_fc for v in stato.disponibili()}


def test_non_viene_mai_consigliato(listone, parametri):
    fantasma = next(g for g in listone if g.ruolo == "a" and g.fvm > 300)
    stato = _stato(listone, parametri, {fantasma.id_fc})
    for reparto in (None, "a"):
        nomi = {
            c.valutazione.giocatore.id_fc
            for c in stato.da_chiamare(limite=20, reparto=reparto)
        }
        assert fantasma.id_fc not in nomi
