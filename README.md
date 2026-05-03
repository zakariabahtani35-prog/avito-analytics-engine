# 🏙️ Avito Real Estate Pipeline — Morocco

> **Pipeline de données immobilières de bout en bout : scraping éthique → nettoyage professionnel → entrepôt PostgreSQL → BI & ML.**

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white"/>
  <img src="https://img.shields.io/badge/ETL-Pipeline-FF6B35?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/BI-Ready-00C49F?style=for-the-badge&logo=powerbi&logoColor=white"/>
  <img src="https://img.shields.io/badge/ML-Ready-A855F7?style=for-the-badge&logo=scikitlearn&logoColor=white"/>
  <img src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge"/>
</p>

<p align="center">
  Pipeline d'ingénierie de données qui transforme des annonces immobilières publiques <strong>Avito.ma</strong> en datasets propres, auditables et directement consommables par Power BI et des modèles Machine Learning.
</p>

**Points clés :**
- ✅ Architecture en couches : Raw → Staging → Clean → Warehouse
- ✅ Pagination avec objectif configurable `SCRAPER_TARGET_LISTINGS=1000`
- ✅ Nettoyage pandas tolérant : mauvaises lignes ignorées, bonnes lignes conservées
- ✅ Traçabilité complète par `batch_id` à chaque exécution
- ✅ Qualité de données validée par assertions programmatiques
- ✅ Modèle en étoile prêt pour Power BI
- ✅ Table plate dédiée à l'entraînement ML
- ✅ Scraping éthique : délais polis, respect `robots.txt`, zéro données personnelles

---

## 📋 Vue d'ensemble

Le marché immobilier marocain manque cruellement de données structurées et exploitables. Les prix varient fortement selon la ville, le quartier et le type de bien — mais ces informations restent fragmentées sur des plateformes d'annonces non analytiques.

Ce pipeline résout ce problème en automatisant l'ensemble du flux :

1. **Collecte** d'annonces publiques depuis Avito.ma avec contraintes éthiques strictes
2. **Nettoyage** professionnel des données brutes : parsing, normalisation, déduplication
3. **Validation** multi-couche pour garantir la cohérence et l'absence d'anomalies
4. **Chargement** dans un entrepôt PostgreSQL structuré en schémas dédiés
5. **Exposition** vers Power BI (modèle en étoile) et ML (table plate)

Le résultat : un dataset immobilier marocain **propre, reproductible et auditable**, prêt pour des analyses décisionnelles sérieuses.

---

## 💼 Valeur métier

Ce pipeline génère de la valeur concrète à plusieurs niveaux d'usage :

| Use Case | Description |
|----------|-------------|
| 📊 **Analyse de marché** | Comparaison des prix par ville, quartier, type de bien |
| 📈 **Suivi des tendances** | Évolution des prix au m² dans le temps par batch |
| 🗺️ **Benchmark géographique** | `price_per_m2` moyen par zone pour détecter les opportunités |
| 🖥️ **Dashboards décisionnels** | Power BI connecté directement à `bi_schema` via modèle en étoile |
| 🤖 **Pricing ML** | Features prêtes à l'emploi pour un modèle de prédiction de prix |
| 🔍 **Détection d'anomalies** | Identification de biens sur ou sous-évalués par rapport au marché |
| 📚 **Recherche académique** | Données structurées pour des études sur le foncier marocain |

---

## 🏗️ Architecture du pipeline

```
┌─────────────────────────────────┐
│       Annonces publiques        │
│          Avito.ma               │
└────────────────┬────────────────┘
                 │  HTTP (poli, robots.txt respecté)
                 ▼
┌─────────────────────────────────┐
│          SCRAPER                │
│   src/extract/scraper.py        │
│   Délais • Arrêt 403/429        │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│         RAW LAYER               │
│   data/raw/avito_raw_<id>.csv   │
│   Données brutes, non altérées  │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│       CLEANING LAYER            │
│   src/clean/clean_data.py       │
│   Parsing • Normalisation       │
│   Déduplication • NULL coercion │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│      VALIDATION LAYER           │
│   src/validation/               │
│   Assertions • Rapports JSON    │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│              PostgreSQL WAREHOUSE                    │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐  │
│  │ staging  │ │  clean   │ │bi_schema │ │ml_sch.│  │
│  │ (brut    │ │ (typé,   │ │(étoile   │ │(table │  │
│  │  contrôlé│ │  propre) │ │ Power BI)│ │ plate)│  │
│  └──────────┘ └──────────┘ └──────────┘ └───────┘  │
└────────────────┬────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
   Power BI           ML Models
  Dashboards        (scikit-learn,
  Analytics          XGBoost…)
```

---

## ⚙️ Design Engineering

Ce pipeline est conçu avec des principes d'ingénierie de données professionnels :

**Persistance brute (Raw Layer)**
Le CSV brut est conservé tel quel avant tout traitement. Cela permet de débugger, rejouer ou auditer n'importe quelle exécution sans rescraper.

**Replayabilité**
L'option `--input-file` permet de réinjecter un Raw CSV existant dans le pipeline de nettoyage et de chargement, sans nouvelle collecte web.

**Traçabilité par batch**
Chaque exécution génère un `batch_id` unique. Toutes les lignes en base portent cet identifiant, permettant d'isoler, comparer ou supprimer n'importe quel batch.

**Séparation des responsabilités**
Chaque couche a une responsabilité unique : `scraper.py` collecte, `clean_data.py` transforme, `load_staging.py` ingère, `run_pipeline.py` orchestre. Pas d'effets de bord entre couches.

**Warehouse-ready**
Les quatre schémas PostgreSQL servent des usages distincts : audit (`staging`), source de vérité (`clean`), consommation analytique (`bi_schema`), entraînement ML (`ml_schema`).

---

## 🗄️ Modélisation de la base de données

| Schéma | Rôle | Contenu |
|--------|------|---------|
| `staging` | Couche tampon | Copie contrôlée des champs bruts autorisés — aucune donnée personnelle |
| `clean` | Source de vérité | Dataset core compact (`clean_listings`) + features optionnelles séparées (`clean_listing_features`) |
| `bi_schema` | Modèle analytique | Schéma en étoile core : `fact_listing` + dimensions temps/localisation |
| `ml_schema` | Features ML | Table plate construite depuis core + features quand disponibles |

**Schéma en étoile (bi_schema)**

Le modèle en étoile sépare les métriques (faits) des attributs descriptifs (dimensions). Power BI charge directement ce schéma : les relations sont préconstruites, les agrégations sont performantes, et les filtres croisés (ville × quartier × date) fonctionnent nativement.

```
       dim_time             dim_location
           │                      │
           └──────┐    ┌──────────┘
                  ▼    ▼
             fact_listing
             (prix, URL, batch_id…)
```

---

## 🛡️ Framework qualité des données

Le module `src/validation/data_quality_checks.py` applique un ensemble d'assertions systématiques après chaque transformation :

**Nettoyage :**
- Suppression des phrases parasites (`il y a X minutes`, `Contacter le vendeur`)
- Parsing robuste des prix (gestion des espaces, virgules, devises)
- Parsing des surfaces, chambres, salles de bain et étages depuis les champs structurés et le titre
- Les features optionnelles restent vides quand elles ne sont pas fiables : aucune valeur inventée
- Déduplication par `listing_url` (contrainte d'unicité forte)
- Rejet des lignes sans titre, prix, localisation, URL, surface fiable, date de scraping ou `batch_id`
- Rejet des prix invalides : `price < 1000` ou `price > 100000000`
- Nettoyage des features : `surface_m2` hors `[10, 2000]`, chambres/SDB hors `[1, 10]`, étage hors `[0, 50]`, `price_per_m2` hors `[100, 100000]` deviennent vides
- Calcul de `price_per_m2 = price / surface_m2` uniquement quand prix et surface sont valides

**Validations post-chargement :**

| Contrôle | Assertion |
|----------|-----------|
| Fichiers présents | Raw CSV, Core Clean CSV et Features CSV existent |
| Variation numérique | Prix, surface et `price_per_m2` restent dans des plages réalistes |
| Absence de données personnelles | Aucun pattern téléphone/email détecté |
| Unicité URL | Zéro doublon sur `listing_url` |
| Champs requis | Les colonnes core et features ne sont jamais vides |
| Cohérence `price_per_m2` | Recalcul via core + features |
| Cohérence BI | `COUNT(fact_listing) = COUNT(clean_listings)` |
| Cohérence ML | `COUNT(ml_property_features) = COUNT(clean_listings)` |
| Intégrité des clés | Toutes les FK du schéma BI résolues |

---

## 🔒 Gouvernance & scraping responsable

Ce projet est conçu avec une éthique de collecte stricte :

**Données collectées — uniquement des champs immobiliers non personnels :**
titre de l'annonce, prix, ville, quartier, surface, chambres, salles de bain, étage, année de construction, URL, date de scraping.

**Données jamais collectées :**
téléphone, email, profil vendeur, nom vendeur, adresse exacte.

**Comportement du scraper :**
- 🎯 Objectif de volume configurable : `SCRAPER_TARGET_LISTINGS=1000`
- 🕐 Délais polis entre chaque requête
- 🔁 Backoff exponentiel plus long sur `429`
- 📜 Lecture stricte de `robots.txt` (mode strict par défaut)
- 🛑 Arrêt automatique sur réponses répétées `403` ou `429`
- 🚫 Aucune tentative de contournement anti-bot
- 🔒 `FETCH_DETAIL_PAGES=false` par défaut (limitation de l'exposition)
- 🔍 Redaction automatique des patterns sensibles détectés dans les textes

> ⚠️ Avant toute exécution réelle, vérifiez que votre usage respecte les conditions d'utilisation d'Avito.ma.

---

## 📦 Artefacts générés

Chaque exécution produit un ensemble d'artefacts identifiés par `batch_id` :

| Artefact | Chemin | Description |
|----------|--------|-------------|
| Raw CSV | `data/raw/avito_raw_<batch_id>.csv` | Données brutes non altérées — base d'audit |
| Core Clean CSV | `data/clean/avito_clean_core_<batch_id>.csv` | Colonnes requises, compactes, jamais vides |
| Features CSV | `data/clean/avito_clean_features_<batch_id>.csv` | Features optionnelles fiables, reliées par `listing_url`; lignes sans aucune feature supprimées |
| Rapport qualité | `data/clean/quality_report_<batch_id>.json` | Rows avant/après, suppressions, valeurs manquantes, outliers |
| Logs | `data/logs/pipeline.log` | Trace complète de l'exécution |

Les CSV intermédiaires garantissent la **reproductibilité** : on peut relire exactement ce qui a été collecté, comparer le brut et le clean, rejouer le chargement sans rescraper, et expliquer toute ligne supprimée lors du nettoyage.

---

## 📁 Structure du projet

```
avito-real-estate-pipeline/
│
├── 📄 docker-compose.yml          # Orchestration Docker (app + db)
├── 🐳 Dockerfile                  # Image applicative Python
├── 📦 requirements.txt            # Dépendances Python
├── 🔑 .env.example                # Template des variables d'environnement
├── 📖 README.md
│
├── sql/
│   ├── 01_create_staging.sql      # Schéma staging
│   ├── 02_create_clean.sql        # Schéma clean
│   ├── 03_create_bi_schema.sql    # Schéma BI (étoile)
│   └── 04_create_ml_schema.sql    # Schéma ML (table plate)
│
├── src/
│   ├── extract/
│   │   └── scraper.py             # Collecte éthique Avito.ma
│   ├── staging/
│   │   └── load_staging.py        # Ingestion vers staging
│   ├── clean/
│   │   └── clean_data.py          # Transformation & nettoyage
│   ├── warehouse/                 # Chargement BI & ML schemas
│   ├── validation/
│   │   └── data_quality_checks.py # Assertions qualité
│   ├── orchestration/
│   │   └── run_pipeline.py        # Point d'entrée principal
│   └── utils/                     # Helpers partagés
│
├── data/
│   ├── raw/                       # CSV bruts par batch
│   ├── clean/                     # CSV propres + rapports JSON
│   └── logs/                      # Logs d'exécution
│
└── tests/                         # Suite pytest
```

---

## 🚀 Démarrage rapide — Windows

**Prérequis :** Python 3.11+, Docker Desktop, Git

```powershell
# 1. Cloner et se positionner
cd C:\Users\pc\Documents\as2\avito-real-estate-pipeline

# 2. Environnement virtuel
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Dépendances
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Configuration
Copy-Item .env.example .env
# Éditer .env avec vos paramètres locaux

# 5. Démarrer PostgreSQL
docker compose up -d db

# 6. Lancer le pipeline
python -m src.orchestration.run_pipeline
```

**Rejouer à partir d'un Raw CSV existant (sans rescraper) :**

```powershell
python -m src.orchestration.run_pipeline `
  --batch-id batch_demo `
  --input-file data/raw/avito_raw_batch_demo.csv
```

> ⚠️ Toujours lancer via `python -m src.orchestration.run_pipeline` (mode module) pour conserver la résolution des imports `src.*`.

---

## 🐳 Exécution Docker

```bash
# 1. Préparer la configuration
cp .env.example .env

# 2. Démarrer la base de données
docker compose up -d db

# 3. Lancer le pipeline en conteneur
docker compose run --rm app
```

---

## 🔎 Validation et inspection

**Inspecter les CSV (PowerShell) :**

```powershell
Get-ChildItem data\raw
Get-ChildItem data\clean
Import-Csv data\raw\avito_raw_<batch_id>.csv | Select-Object -First 10
Import-Csv data\clean\avito_clean_core_<batch_id>.csv | Select-Object -First 20
Import-Csv data\clean\avito_clean_features_<batch_id>.csv | Select-Object -First 20
Get-Content data\clean\quality_report_<batch_id>.json
```

**Connexion PostgreSQL (Docker) :**

```powershell
docker compose exec db psql -U postgres -d avito_db
```

**Requêtes de validation essentielles :**

```sql
-- Comptages par couche
SELECT COUNT(*) FROM staging.raw_listings;
SELECT COUNT(*) FROM clean.clean_listings;
SELECT COUNT(*) FROM bi_schema.fact_listing;
SELECT COUNT(*) FROM ml_schema.ml_property_features;

-- Statistiques de marché
SELECT
  MIN(price)          AS prix_min,
  MAX(price)          AS prix_max,
  ROUND(AVG(price))   AS prix_moyen,
  MIN(f.surface_m2)   AS surface_min,
  MAX(f.surface_m2)   AS surface_max,
  ROUND(AVG(f.surface_m2), 1) AS surface_moyenne,
  ROUND(AVG(f.price_per_m2))  AS prix_m2_moyen
FROM clean.clean_listings c
LEFT JOIN clean.clean_listing_features f
  ON f.listing_url = c.listing_url;

-- Distribution par batch
SELECT batch_id, COUNT(*) AS lignes
FROM clean.clean_listings
GROUP BY batch_id
ORDER BY batch_id DESC;

-- Benchmark par ville et quartier
SELECT
  c.city,
  c.district,
  COUNT(*)                         AS annonces,
  ROUND(AVG(f.price_per_m2), 2)    AS prix_m2_moyen
FROM clean.clean_listings c
LEFT JOIN clean.clean_listing_features f
  ON f.listing_url = c.listing_url
GROUP BY c.city, c.district
ORDER BY annonces DESC;
```

---

## 🧪 Tests

```powershell
python -m pytest
```

La suite couvre : les transformations de nettoyage, les validations qualité, l'intégrité des clés étrangères et la cohérence des comptages entre couches.

---

## 🔮 Roadmap

- [ ] 📊 Dashboards Power BI connectés à `bi_schema` (star schema natif)
- [ ] 🔄 Orchestration Apache Airflow avec DAG schedulé
- [ ] 🧱 Modèles dbt pour la couche de transformation déclarative
- [ ] ✅ Great Expectations pour la validation contractuelle des données
- [ ] 🤖 Modèle ML de prédiction de prix (XGBoost / scikit-learn)
- [ ] 🌐 API REST FastAPI exposant les données nettoyées
- [ ] 📡 Monitoring automatisé et alertes qualité
- [ ] ⚙️ CI/CD GitHub Actions (lint, tests, déploiement)

---

## 🎯 Compétences démontrées

Ce projet illustre une maîtrise concrète et intégrée des disciplines suivantes :

| Domaine | Compétence |
|---------|------------|
| **Python** | Scraping, parsing, transformation de données, CLI |
| **Data Engineering** | Pipeline ETL complet, couches Raw/Staging/Clean/Warehouse |
| **PostgreSQL** | Modélisation multi-schémas, star schema, intégrité référentielle |
| **Analytics Engineering** | Modèle en étoile prêt pour Power BI |
| **ML Preparation** | Feature engineering, table plate, variables dérivées |
| **Data Quality** | Assertions programmatiques, rapports JSON, contrôles de cohérence |
| **Data Governance** | Scraping éthique, zéro donnée personnelle, traçabilité complète |
| **Docker** | Conteneurisation, `docker-compose`, environnements reproductibles |
| **Software Design** | Séparation des responsabilités, replayabilité, traçabilité par batch |

---

## ⚙️ Variables d'environnement

Copier `.env.example` vers `.env` et adapter les valeurs locales. Aucun identifiant n'est hardcodé dans le code source.

```env
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=avito_db
DB_USER=postgres
DB_PASSWORD=change_me
```

---

## ⚠️ Limites connues

- Les sélecteurs HTML Avito peuvent évoluer et nécessiter une mise à jour du scraper.
- Les annonces sans prix ou surface fiable sont rejetées du dataset clean.
- La qualité finale dépend de la richesse du HTML disponible au moment du scraping.
- Pour une évaluation académique : inspecter systématiquement le Raw CSV, le Clean CSV, le rapport qualité et les tables PostgreSQL.

---

<p align="center">
  <sub>Projet réalisé dans un objectif d'ingénierie de données appliquée au marché immobilier marocain.</sub>
</p>
