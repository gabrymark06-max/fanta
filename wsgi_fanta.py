"""Il punto d'ingresso della web app, da solo o insieme a un altro progetto.

PERCHE' NON SI CHIAMA `wsgi.py`. Sul piano gratuito di PythonAnywhere la web
app e' **una sola**, e li' ne gira gia' un'altra: due progetti sulla stessa
web app finiscono tutti e due su `sys.path`, e due file chiamati `wsgi.py`
diventerebbero lo stesso modulo — vincerebbe quello caricato per primo, in
silenzio. Un nome diverso costa niente e toglie di mezzo la classe di bug piu'
antipatica che ci sia: quella in cui il codice che gira non e' quello che
stai leggendo.

DUE MODI DI USARLO.

Da solo, quando la web app e' tutta tua — il file WSGI di PythonAnywhere
diventa:

    import sys
    sys.path.insert(0, "/home/UTENTE/fanta")
    from wsgi_fanta import application  # noqa

Insieme a un altro progetto, che e' il caso vero qui:

    import sys
    sys.path.insert(0, "/home/UTENTE/altro-progetto")
    sys.path.insert(0, "/home/UTENTE/fanta")
    from bot import app as altra            # l'app che c'era gia'
    from wsgi_fanta import affianca
    application = affianca("/fanta", altra)

L'altro progetto **non si tocca**: non un import, non una rotta, non una riga.
Chi arriva sotto `/fanta` finisce qui, tutto il resto passa a lui esattamente
come prima. E' il minimo intervento possibile su un sistema che gia' funziona,
e su un sistema che gia' funziona il minimo intervento e' anche il migliore.
"""

from __future__ import annotations

import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent
if str(RADICE / "src") not in sys.path:
    sys.path.insert(0, str(RADICE / "src"))

from fantabot.bot.web import application  # noqa: E402


def affianca(prefisso: str, altra, mia=application):
    """Monta il fantabot sotto `prefisso`, e lascia il resto all'altra app.

    Il prefisso viene tolto da `PATH_INFO` e spostato in `SCRIPT_NAME`, come
    vuole lo standard WSGI: cosi' l'app montata vede il percorso che si
    aspetta e non sa nemmeno di stare sotto un prefisso.
    """
    prefisso = "/" + prefisso.strip("/")

    def instrada(environ, start_response):
        percorso = environ.get("PATH_INFO", "")
        if percorso == prefisso or percorso.startswith(prefisso + "/"):
            environ = dict(environ)
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + prefisso
            environ["PATH_INFO"] = percorso[len(prefisso) :]
            return mia(environ, start_response)
        return altra(environ, start_response)

    return instrada


__all__ = ["application", "affianca"]
