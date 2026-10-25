"""
Facteurs d'émission (kg CO₂e par kg d'aliment) — SOURCE UNIQUE pour toute l'application.

Les valeurs viennent de la table `impact.FacteurImpact` (référentiel sourcé, modifiable dans /admin/) :
le module repas (empreinte d'un repas, « Et si… », forêt, bilan) et le module impact affichent ainsi
exactement les mêmes chiffres. Lecture seule : ce module ne modifie jamais le référentiel.

Repli sur les valeurs par défaut ci-dessous si la table est vide ou indisponible.
Petit cache mémoire (60 s), vidé dès qu'un facteur est modifié dans l'admin (signal, voir apps.py).
"""
import time
from collections.abc import Mapping

from django.db import DatabaseError

# Valeurs de repli, d'après Poore & Nemecek (2018), Science 360:987 (moyennes par catégorie).
DEFAUTS = {
    "VIANDE_ROUGE": 60.0,
    "VOLAILLE": 9.9,
    "POISSON": 13.6,
    "LAITIER": 9.0,
    "LEGUMINEUSE": 1.0,
    "FECULENT": 1.6,
    "FRUIT_LEGUME": 0.7,
}
DUREE_CACHE_S = 60


class FacteursCO2(Mapping):
    """Se lit comme un dict : FACTEURS_CO2["VIANDE_ROUGE"] -> 35.0 (valeur du référentiel)."""

    def __init__(self):
        self._valeurs, self._charge_le = None, 0.0

    def _charger(self):
        if self._valeurs is None or time.monotonic() - self._charge_le > DUREE_CACHE_S:
            valeurs = dict(DEFAUTS)
            try:
                from impact.models import FacteurImpact
                for categorie, co2 in FacteurImpact.objects.filter(categorie__in=DEFAUTS).values_list(
                        "categorie", "co2_kg_par_kg"):
                    valeurs[categorie] = float(co2)
            except (ImportError, LookupError, DatabaseError):
                pass                                  # référentiel indisponible : valeurs par défaut
            self._valeurs, self._charge_le = valeurs, time.monotonic()
        return self._valeurs

    def invalider(self, **kwargs):
        self._valeurs = None

    def __getitem__(self, categorie):
        return self._charger()[categorie]

    def __iter__(self):                               # les catégories sont fixes : pas de requête
        return iter(DEFAUTS)

    def __len__(self):
        return len(DEFAUTS)

    def __contains__(self, categorie):
        return categorie in DEFAUTS

    def en_dict(self):
        return dict(self._charger())


FACTEURS_CO2 = FacteursCO2()
