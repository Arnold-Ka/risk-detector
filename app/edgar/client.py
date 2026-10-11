"""Client HTTP pour SEC EDGAR — la manière polie de parler à la SEC.

Règles de la SEC qu'il faut RESPECTER (feuille de route §3) :
  - 10 requêtes par seconde maximum => au moins 100 ms entre deux requêtes ;
  - le User-Agent doit contenir un nom + e-mail réels (réglé dans `.env`,
    lu via app.config.settings.sec_user_agent) ;
  - mettre les réponses en cache plutôt que de re-interroger EDGAR à
    chaque visite d'utilisateur.

Ce module implémente le rate limit + le User-Agent. Le cache fichier
(settings.cache_dir) et les téléchargements massifs en ZIP sont des TODO
de la phase 1.
"""

import time
import unicodedata

import httpx

from app.config import settings

# 10 requêtes/seconde == une requête toutes les 1/10 s == écart minimum
# de 0.1 s.
MIN_INTERVAL = 0.1


class EdgarClient:
    def __init__(self):
        # Horodatage (monotone) de la requête précédente ; utilisé par get()
        # pour calculer combien il faut encore attendre. 0.0 = « jamais
        # appelé pour l'instant ».
        self._last = 0.0

        # httpx.Client réutilise une connexion TCP entre requêtes (plus
        # rapide que de créer un client par appel) et porte le User-Agent
        # obligatoire sur chaque requête automatiquement.
        #
        # CORRECTIF : httpx encode les valeurs d'en-tête en ASCII et levait
        # UnicodeEncodeError sur « Prénom » (é). Les en-têtes HTTP sont en
        # ASCII en pratique (RFC 7230) ; translittérer plutôt que planter —
        # la SEC demande seulement un nom + e-mail identifiable, les accents
        # sont facultatifs.
        user_agent = (
            unicodedata.normalize("NFKD", settings.sec_user_agent)
            .encode("ascii", "ignore")
            .decode()
        )
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=30,  # secondes ; EDGAR peut être lent, mais ne jamais
            #             rester bloqué pour toujours
        )

    def get(self, url: str) -> bytes:
        """GET `url` en respectant le budget de 10 req/s, renvoie les octets.

        Synchrone volontairement : les téléchargements massifs tournent dans
        jobs/nightly.py, où une simple boucle avec sleep est plus facile à
        raisonner qu'un asyncio.
        """
        # Combien de l'écart de 0.1 s reste-t-il depuis la dernière requête ?
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

        # CORRECTIF : c'était `time.monotonic` (sans parenthèses) — cela
        # stockait la FONCTION elle-même, donc l'appel suivant plantait avec
        # `TypeError: unsupported operand type(s) for -: 'float' and 'function'`.
        self._last = time.monotonic()

        # raise_for_status() : un 4xx/5xx (ex. 403 quand la SEC nous bannit
        # pour un mauvais User-Agent, 404 pour un CIK erroné) doit planter
        # bruyamment, pas être mis en cache silencieusement comme des
        # données.
        resp = self._http.get(url)
        resp.raise_for_status()
        return resp.content

# TODO(phase 1) : cache fichier indexé par URL sous settings.cache_dir pour
# qu'un redémarrage de job (ou un second passage) ne re-touche pas EDGAR.
