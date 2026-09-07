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
