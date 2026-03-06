# Dispo entre amis

[App here](https://planner-perso.streamlit.app/)

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

## Base de donnees

Par defaut, l'application utilise SQLite dans `data/planner.db`.

Pour utiliser PostgreSQL ou Supabase, definissez `DATABASE_URL` :

```env
DATABASE_URL=postgresql://...
```

En local, l'application lit automatiquement `.env`.
Sur Streamlit Community Cloud, ajoutez `DATABASE_URL` dans les secrets de l'application.

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
