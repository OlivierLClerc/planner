# Dispo entre amis

Application Streamlit en francais pour creer des sondages de dates et laisser chaque participant voter avec trois niveaux:

- `0` = indisponible
- `1` = peut-etre
- `2` = disponible

## Demarrage

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Fonctionnalites

- creation de plusieurs sondages via un slug partageable
- stockage persistant en SQLite dans `data/planner.db`
- connexion participant par `nom + code secret`
- calendrier interactif avec clic simple ou glisser-deposer
- infobulle avec les noms des personnes disponibles ou peut-etre
- intensite de couleur basee sur le score collectif

## Tests

```powershell
python -m unittest discover -s tests
```
