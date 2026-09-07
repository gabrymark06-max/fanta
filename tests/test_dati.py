"""Il livello dati: leggere il listone, e ritrovare un nome scritto di fretta.

Il parser lavora su una fixture e non sulla rete: un test che dipende da un
sito non e' un test, e la sera dell'asta serve sapere se e' cambiato il sito o
se ho rotto io qualcosa.
"""

from __future__ import annotations

from fantabot.dati.aggiorna import _coppia_rigori, normalizza
from fantabot.dati.fantacalcio import analizza_tabella
from fantabot.dati.magazzino import cerca

LISTONE = """
<table><tbody>
<tr class="player-row" data-filter-role-classic="a" data-filter-role-mantra="pc">
  <th class="player-name">
    <a class="player-name player-link"
       href="https://www.fantacalcio.it/serie-a/squadre/inter/martinez-l/2764">
       <span>Martinez L.</span></a>
  </th>
  <td class="player-team" data-col-key="sq">INT</td>
  <td data-col-key="c_qi">35</td>
  <td data-col-key="c_qa">33</td>
  <td data-col-key="c_fvm">361</td>
</tr>
<tr class="player-row" data-filter-role-classic="p" data-filter-role-mantra="por">
  <th class="player-name">
    <a class="player-name player-link"
       href="https://www.fantacalcio.it/serie-a/squadre/milan/maignan/2542/2025-26">
       <span>Maignan</span></a>
  </th>
  <td class="player-team" data-col-key="sq">MIL</td>
  <td data-col-key="pg">37</td>
  <td data-col-key="mv">6,12</td>
  <td data-col-key="mfv">5,32</td>
  <td data-col-key="rig">0 / 0</td>
</tr>
<tr class="player-row"><td>riga senza link, da saltare</td></tr>
</tbody></table>
"""


def test_legge_le_righe_e_ignora_quelle_senza_giocatore():
    righe = analizza_tabella(LISTONE)
    assert len(righe) == 2
    assert [r.nome for r in righe] == ["Martinez L.", "Maignan"]


def test_estrae_id_squadra_ruolo_e_valori():
    lautaro = analizza_tabella(LISTONE)[0]
    assert lautaro.id_fc == 2764
    assert lautaro.squadra == "INT"
    assert lautaro.ruolo_classic == "a"
    assert lautaro.ruolo_mantra == "pc"
    assert lautaro.numero("c_qa") == 33
    assert lautaro.numero("c_fvm") == 361


def test_l_id_si_legge_anche_quando_l_url_porta_la_stagione():
    """Le pagine delle statistiche mettono la stagione in coda all'URL.

    Leggendo l'ultimo numero si finiva per prendere "26" da "2025-26", e il
    listone non si agganciava piu' alle statistiche: nessun errore, solo
    seicento giocatori improvvisamente senza passato.
    """
    maignan = analizza_tabella(LISTONE)[1]
    assert maignan.id_fc == 2542


def test_i_numeri_con_la_virgola_e_le_celle_vuote():
    maignan = analizza_tabella(LISTONE)[1]
    assert maignan.numero("mv") == 6.12
    assert maignan.numero("mfv") == 5.32
    assert maignan.numero("non_esiste") == 0.0
    assert maignan.numero("non_esiste", default=7.0) == 7.0


def test_i_rigori_sono_segnati_su_calciati():
    assert _coppia_rigori("3 / 5") == (3, 5)
    assert _coppia_rigori("0 / 0") == (0, 0)
    assert _coppia_rigori("") == (0, 0)
    assert _coppia_rigori("-") == (0, 0)


def test_normalizza_toglie_accenti_punti_e_maiuscole():
    assert normalizza("Vlahović") == "vlahovic"
    assert normalizza("Martinez L.") == "martinez l"
    assert normalizza("  DE  ROSSI ") == "de rossi"


def test_cerca_per_prefisso_poi_per_pezzo_poi_per_somiglianza(conn_popolato):
    conn_popolato.execute(
        """
        INSERT INTO giocatori (id_fc, nome, nome_cerca, squadra, ruolo,
                               quota_iniziale, quota_attuale, fvm)
        VALUES (5001, 'Vlahovic', 'vlahovic', 'JUV', 'a', 20, 20, 120),
               (5002, 'Donnarumma', 'donnarumma', 'MIL', 'p', 18, 18, 80),
               (5003, 'Martinez L.', 'martinez l', 'INT', 'a', 33, 33, 361),
               (5004, 'Martinez Jo.', 'martinez jo', 'INT', 'p', 17, 17, 68)
        """
    )
    conn_popolato.commit()

    assert [r["nome"] for r in cerca(conn_popolato, "vla")] == ["Vlahovic"]
    # Due omonimi: li restituisce entrambi, il piu' quotato per primo.
    nomi = [r["nome"] for r in cerca(conn_popolato, "martinez")]
    assert nomi == ["Martinez L.", "Martinez Jo."]
    # Errore di battitura: la somiglianza recupera comunque.
    assert cerca(conn_popolato, "donnaruma")[0]["nome"] == "Donnarumma"
    assert cerca(conn_popolato, "zzzzzz") == []
    assert cerca(conn_popolato, "   ") == []
