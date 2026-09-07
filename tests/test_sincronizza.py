"""Il file che viaggia da GitHub Actions al bot, e cosa non deve portarsi via.

Il test che conta davvero e' il primo: ogni tabella dello schema sta in
esattamente uno dei due elenchi. Senza, una migrazione futura aggiungerebbe
una tabella che nessuno ha classificato, e il primo sync la cancellerebbe —
o non la aggiornerebbe mai, che si scopre solo mesi dopo.
"""

from __future__ import annotations

from fantabot.dati import sincronizza
from fantabot.db import connetti


def test_ogni_tabella_e_classificata(conn):
    """Nessuna tabella dimenticata, e nessuna in tutti e due gli elenchi."""
    schema = sincronizza.tabelle_dello_schema(conn)
    classificate = set(sincronizza.DI_RIFERIMENTO) | set(sincronizza.MIE)
    assert schema - classificate == set(), "tabelle non classificate"
    assert classificate - schema == set(), "elenchi che nominano tabelle inesistenti"
    assert not set(sincronizza.DI_RIFERIMENTO) & set(sincronizza.MIE)


def _con_una_lega(conn):
    conn.execute(
        "INSERT INTO leghe (chat_id, nome) VALUES (?, ?)", (42, "La mia lega")
    )
    conn.execute(
        "INSERT INTO squadre (id_lega, nome, e_mia) VALUES (1, 'La mia squadra', 1)"
    )
    conn.execute(
        "INSERT INTO acquisti (id_lega, id_fc, id_squadra, prezzo)"
        " VALUES (1, 1, 1, 77)"
    )
    conn.execute(
        "INSERT INTO mercato_esterno (id_fc, prezzo_medio, fascia)"
        " VALUES (1, 30.0, 1)"
    )
    conn.commit()


def test_l_esportazione_non_si_porta_via_la_lega(conn_popolato, tmp_path):
    """Il file che viaggia deve poter finire in un log senza svelare niente."""
    _con_una_lega(conn_popolato)
    fuori = tmp_path / "riferimento.sqlite3"
    esito = sincronizza.esporta(conn_popolato, fuori)
    assert esito.riuscito and esito.tabelle["giocatori"] > 0

    portato = connetti(fuori)
    for tabella in sincronizza.MIE:
        quante = portato.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
        assert quante == 0, f"{tabella} non doveva viaggiare"
    portato.close()


def test_assorbire_non_tocca_quello_che_e_mio(conn_popolato, tmp_path, listone):
    """La prova che vale: un sync a meta' asta non cancella l'asta."""
    _con_una_lega(conn_popolato)

    # Un mondo aggiornato, che arriva da fuori con un listone diverso.
    altrove = connetti(tmp_path / "altrove.sqlite3")
    altrove.execute(
        "INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo, fvm)"
        " VALUES (777, 'Nuovo', 'nuovo', 'ATA', 'a', 300)"
    )
    altrove.commit()
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(altrove, pacco)
    altrove.close()

    esito = sincronizza.assorbi(conn_popolato, pacco)
    assert esito.riuscito

    # Il listone e' quello nuovo…
    nomi = [r[0] for r in conn_popolato.execute("SELECT nome FROM giocatori")]
    assert nomi == ["Nuovo"]
    # …e l'asta e' ancora tutta li'.
    assert conn_popolato.execute("SELECT COUNT(*) FROM leghe").fetchone()[0] == 1
    assert conn_popolato.execute(
        "SELECT prezzo FROM acquisti"
    ).fetchone()[0] == 77
    assert conn_popolato.execute(
        "SELECT COUNT(*) FROM mercato_esterno"
    ).fetchone()[0] == 1


def test_una_tabella_arrivata_vuota_non_cancella_quella_di_prima(
    conn_popolato, tmp_path
):
    """Una lettura andata male dall'altra parte non deve svuotare il bot.

    E' il caso che succede davvero: fantacalcio.it che risponde 503 mentre
    Actions gira, e un file che parte con dentro zero giocatori.
    """
    quanti = conn_popolato.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
    vuoto = connetti(tmp_path / "vuoto.sqlite3")
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(vuoto, pacco)
    vuoto.close()

    esito = sincronizza.assorbi(conn_popolato, pacco)
    assert esito.riuscito
    assert (
        conn_popolato.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
        == quanti
    )


def test_un_file_che_non_esiste_lo_dice(conn_popolato, tmp_path):
    esito = sincronizza.assorbi(conn_popolato, tmp_path / "manco.sqlite3")
    assert not esito.riuscito
    assert "non trovo" in esito.errore


def test_un_file_che_non_e_un_database_non_rompe_niente(conn_popolato, tmp_path):
    finto = tmp_path / "riferimento.sqlite3"
    finto.write_bytes(b"non sono un database")
    quanti = conn_popolato.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
    esito = sincronizza.assorbi(conn_popolato, finto)
    assert not esito.riuscito
    assert (
        conn_popolato.execute("SELECT COUNT(*) FROM giocatori").fetchone()[0]
        == quanti
    )


def test_andata_e_ritorno_conserva_i_numeri(conn_popolato, tmp_path):
    prima = {
        t: conn_popolato.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in sincronizza.DI_RIFERIMENTO
    }
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(conn_popolato, pacco)
    vuoto = connetti(tmp_path / "arrivo.sqlite3")
    esito = sincronizza.assorbi(vuoto, pacco)
    assert esito.riuscito
    for tabella, quante in prima.items():
        if quante:
            assert (
                vuoto.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
                == quante
            )
    vuoto.close()


def test_una_squalifica_scontata_sparisce(conn_popolato, tmp_path):
    """Il vuoto degli squalificati e' uno stato, non un guasto.

    Per gran parte della stagione non e' squalificato nessuno. Se quel vuoto
    valesse come lettura fallita, una squalifica scontata non verrebbe mai
    cancellata e il bot terrebbe quel giocatore in panchina per sempre.
    """
    conn_popolato.execute(
        "INSERT INTO squalifiche (id_fc, giornate) VALUES (1, 2)"
    )
    conn_popolato.commit()

    mondo = connetti(tmp_path / "mondo.sqlite3")
    mondo.execute(
        "INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo, fvm)"
        " VALUES (1, 'Tizio', 'tizio', 'ATA', 'a', 10)"
    )
    mondo.commit()
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(mondo, pacco)
    mondo.close()

    assert sincronizza.assorbi(conn_popolato, pacco).riuscito
    assert conn_popolato.execute(
        "SELECT COUNT(*) FROM squalifiche"
    ).fetchone()[0] == 0


def test_le_tabelle_che_non_possono_essere_vuote_sono_di_riferimento():
    assert set(sincronizza.MAI_VUOTE) <= set(sincronizza.DI_RIFERIMENTO)


def test_il_listone_si_sostituisce_anche_con_minuti_e_infortuni_dentro(
    conn_popolato, tmp_path
):
    """Il caso normale sul bot vero, e quello che rompeva tutto.

    `campo`, `infortuni` e `squalifiche` puntano a `giocatori`. Svuotare il
    listone per rimetterlo nuovo lasciava quelle righe appese per un istante,
    e SQLite rifiutava l'intera transazione: il sync non sarebbe mai riuscito
    una volta sola, su un database in uso.
    """
    conn_popolato.executemany(
        "INSERT INTO campo (id_fc, minuti, presenze, giornate_squadra)"
        " VALUES (?, 270, 3, 3)",
        [(1,), (2,), (3,)],
    )
    conn_popolato.execute(
        "INSERT INTO infortuni (id_fc, testo, giornate_fuori)"
        " VALUES (2, 'lesione', 4)"
    )
    conn_popolato.execute("INSERT INTO squalifiche (id_fc, giornate) VALUES (3, 1)")
    conn_popolato.commit()

    mondo = connetti(tmp_path / "mondo.sqlite3")
    mondo.executemany(
        "INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo, fvm)"
        " VALUES (?, ?, ?, 'ATA', 'a', 10)",
        [(500, "Nuovo", "nuovo"), (501, "Altro", "altro")],
    )
    mondo.execute(
        "INSERT INTO campo (id_fc, minuti, presenze, giornate_squadra)"
        " VALUES (500, 90, 1, 1)"
    )
    mondo.commit()
    pacco = tmp_path / "riferimento.sqlite3"
    sincronizza.esporta(mondo, pacco)
    mondo.close()

    esito = sincronizza.assorbi(conn_popolato, pacco)
    assert esito.riuscito, esito.errore
    assert sorted(
        r[0] for r in conn_popolato.execute("SELECT id_fc FROM giocatori")
    ) == [500, 501]
    assert [r[0] for r in conn_popolato.execute("SELECT id_fc FROM campo")] == [500]
    # Niente righe orfane: chi non e' piu' in listone non e' piu' fermo.
    assert conn_popolato.execute(
        "SELECT COUNT(*) FROM infortuni"
    ).fetchone()[0] == 0
