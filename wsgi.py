"""Il file che PythonAnywhere apre per servire la web app.

Nella pagina Web della dashboard, alla voce «WSGI configuration file», il
contenuto deve essere questo — o due righe che importano questo:

    import sys
    sys.path.insert(0, "/home/TUO_UTENTE/fanta")
    from wsgi import application  # noqa

Non c'e' altro da configurare: il resto lo legge dal `.env` che sta accanto.
"""

from __future__ import annotations

import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent
sys.path.insert(0, str(RADICE / "src"))

from fantabot.bot.web import application  # noqa: E402

__all__ = ["application"]
