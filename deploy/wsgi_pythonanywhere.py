"""File WSGI della web app GabryMark.pythonanywhere.com.

Scritto per fare il passaggio da pronostici al fantabot SENZA UNA FINESTRA IN
CUI NON RISPONDE NIENTE.

Il fantabot ha bisogno di python-telegram-bot 21.9; pronostici usa la 13.15,
e i due progetti condividono lo stesso site-packages, quindi non possono
convivere. Finche' la 21.9 non e' installata, qui sotto l'import del fantabot
fallisce e serve pronostici come ha sempre fatto. Appena si lancia

    bash ~/fanta/installa.sh

e si ricarica la web app, l'import riesce e il fantabot prende il posto.
Il passaggio avviene da solo, nel momento giusto, e in mezzo non c'e' nessun
istante in cui l'indirizzo risponde con un errore.

QUALE DEI DUE E' PARTITO lo dice il log della web app: si legge dalla
dashboard, alla voce Log files -> error log. Non e' un dettaglio da poco —
una scelta automatica che non dice quale strada ha preso e' esattamente il
tipo di cosa che ti fa perdere un'ora a chiederti perche' il bot non risponde.

PER TORNARE INDIETRO basta rimettere le tre righe di prima:

    import sys
    sys.path.insert(0, '/home/GabryMark/pronostici')
    from bot import app as application

(e disinstallare la 21.9: `python3.10 -m pip install --user
"python-telegram-bot==13.15"`).
"""

import sys

sys.path.insert(0, "/home/GabryMark/fanta")

try:
    from wsgi_fanta import application  # noqa: F401

    print("WSGI: parte il fantabot", file=sys.stderr)
except Exception as errore:  # python-telegram-bot 21.9 non ancora installato
    print(
        f"WSGI: fantabot non disponibile ({errore!r}), resta pronostici. "
        "Per passare: bash ~/fanta/installa.sh, poi ricarica la web app.",
        file=sys.stderr,
    )
    sys.path.insert(0, "/home/GabryMark/pronostici")
    from bot import app as application  # noqa: F401
