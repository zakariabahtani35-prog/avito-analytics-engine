<div align="center">

# AVITO REAL ESTATE DATA PLATFORM
### *Morocco · End-to-End Data Engineering*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![ETL Pipeline](https://img.shields.io/badge/Pattern-ETL%20Pipeline-FF6B35?style=flat-square)]()
[![BI Ready](https://img.shields.io/badge/BI-Power%20BI%20Ready-F2C811?style=flat-square&logo=powerbi&logoColor=black)]()
[![ML Ready](https://img.shields.io/badge/ML-Feature%20Store%20Ready-A855F7?style=flat-square&logo=scikitlearn&logoColor=white)]()
[![Warehouse](https://img.shields.io/badge/Warehouse-Star%20Schema-00C49F?style=flat-square)]()

<br/>

**Plateforme de données immobilières entièrement reproductible, conçue avec une éthique de collecte stricte et une architecture warehouse-first — transformant les annonces publiques Avito.ma en datasets analytiques et ML-ready exploitables en production.**

<br/>

</div>

---

## Problème & Proposition de Valeur

Le marché immobilier marocain souffre d'un manque structurel de données exploitables. Les prix varient considérablement selon la ville, le quartier et le type de bien, mais cette information reste fragmentée sur des plateformes non analytiques — inaccessible à quiconque souhaite prendre des décisions éclairées.

Cette plateforme répond à ce problème avec un pipeline de données de bout en bout qui :

- **Collecte** de manière éthique et reproductible des annonces immobilières publiques
- **Transforme** les données brutes en datasets de qualité production, documentés et auditables
- **Charge** un entrepôt PostgreSQL multi-schémas prêt pour Power BI et le Machine Learning
- **Valide** chaque couche de données avec des assertions programmatiques et des rapports de qualité

Le résultat est un **actif de données structuré, traçable et réutilisable** — là où il n'existait auparavant qu'une série de pages HTML.

---

## Architecture Générale

```
╔══════════════════════════════════════════════════════════════════════╗
║                     SOURCE — Avito.ma (Public)                       ║
║                Annonces immobilières · HTTP poli                     ║
╚══════════════════════════╦═══════════════════════════════════════════╝
                           ║
                           ▼
╔══════════════════════════════════════════════════════════════════════╗
║  EXTRACTION LAYER — src/extract/scraper.py                           ║
║  Pagination configurable · Délais polis · Backoff exponentiel        ║
║  robots.txt strict · Arrêt automatique 403/429 · Zéro PII            ║
╚══════════════════════════╦═══════════════════════════════════════════╝
                           ║  batch_id unique par exécution
                           ▼
╔══════════════════════════════════════════════════════════════════════╗
║  RAW LAYER — data/raw/avito_raw_<batch_id>.csv                       ║
║  Source of truth immuable · Aucune transformation · Base d'audit     ║
╚══════════════════════════╦═══════════════════════════════════════════╝
                           ║
                           ▼
╔══════════════════════════════════════════════════════════════════════╗
║  CLEANING ENGINE — src/clean/clean_data.py                           ║
║  Parsing regex · Normalisation · Déduplication URL · NULL coercion   ║
║  Rejet des lignes invalides · Calcul price_per_m2 · Séparation Core  ║
╚═══════════════════════╦══════════════════════╦════════════════════════╝
                        ║                      ║
                        ▼                      ▼
              avito_clean_core_*.csv    avito_clean_features_*.csv
                        ║                      ║
                        ▼                      ▼
╔══════════════════════════════════════════════════════════════════════╗
║  VALIDATION LAYER — src/validation/data_quality_checks.py            ║
║  Assertions programmatiques · Rapports JSON · Intégrité référentielle║
╚══════════════════════════╦═══════════════════════════════════════════╝
                           ║
                           ▼
╔══════════════════════════════════════════════════════════════════════╗
║                    PostgreSQL WAREHOUSE                               ║
║                                                                      ║
║   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌───────────┐  ║
║   │  staging   │   │   clean    │   │ bi_schema  │   │ ml_schema │  ║
║   │ (tampon    │   │ (source    │   │  (étoile   │   │  (table   │  ║
║   │  contrôlé) │   │ de vérité) │   │ Power BI)  │   │   plate)  │  ║
║   └────────────┘   └────────────┘   └────────────┘   └───────────┘  ║
╚═══════════════════════╦══════════════════════╦════════════════════════╝
                        ║                      ║
                        ▼                      ▼
                  Power BI / BI            Scikit-learn
                  Dashboards               XGBoost · ML
```

---

## Principes d'Ingénierie

### Replayabilité & Découplage des couches

Chaque couche est indépendante. Le Raw CSV est l'artefact immuable de référence : on peut rejouer intégralement le nettoyage et le chargement à partir d'un fichier existant, sans re-scraper.

```bash
# Rejouer à partir d'un Raw CSV existant — zéro re-collecte
python -m src.orchestration.run_pipeline \
  --batch-id batch_demo \
  --input-file data/raw/avito_raw_batch_demo.csv
```

### Traçabilité par Batch

Chaque exécution génère un `batch_id` unique. Toutes les lignes en base portent cet identifiant — permettant d'isoler, comparer, supprimer ou auditer n'importe quel batch sans affecter les données des autres exécutions.

### Séparation des Responsabilités

| Module | Responsabilité unique |
|--------|-----------------------|
| `scraper.py` | Collecte HTTP éthique |
| `clean_data.py` | Transformation & standardisation |
| `load_staging.py` | Ingestion staging |
| `warehouse/` | Population BI & ML schemas |
| `data_quality_checks.py` | Validation & assertions |
| `run_pipeline.py` | Orchestration sans logique métier |

### Warehouse-First Design

Le pipeline est conçu pour alimenter un entrepôt, pas un fichier. Les quatre schémas PostgreSQL servent des usages distincts et contractualisés : aucune couche n'est un artefact jetable.

---

## Système de Collecte

Le scraper est conçu pour être un citoyen responsable du web :

- **Volume configurable** : `SCRAPER_TARGET_LISTINGS=10000` — objectif déclaratif, pas une boucle infinie
- **Délais polis** entre chaque requête HTTP
- **Backoff exponentiel** sur `429 Too Many Requests`
- **Lecture stricte de `robots.txt`** (mode strict activé par défaut)
- **Arrêt automatique** sur réponses répétées `403` ou `429`
- **Aucune tentative de contournement** des mécanismes anti-bot
- **`FETCH_DETAIL_PAGES=true`** par défaut — extraction détaillée des attributs quand le site l'autorise
- **Redaction automatique** des patterns sensibles dans les textes extraits
- **Zéro PII collectée** : téléphone, email, profil vendeur — jamais collectés

> **Champs collectés uniquement** : titre, description, prix, ville, quartier, type de bien, type d'annonce (`sale`/`rent`), surface, chambres, salles de bain, étage, coordonnées si disponibles, attributs publics de l'annonce, année de construction, URL, date de scraping.

---

## Moteur de Nettoyage & Standardisation

`clean_data.py` applique un pipeline de transformation déterministe et tolérant aux fautes :

**Parsing & Extraction**
- Extraction prix par regex multi-pattern (espaces, virgules, devises MAD/DH)
- Extraction surface depuis champs structurés et titre en fallback
- Parsing chambres, salles de bain, étage depuis les attributs HTML
- Suppression des phrases parasites (`il y a X minutes`, `Contacter le vendeur`)

**Normalisation**
- Normalisation ville et quartier en minuscules stripped
- Calcul `price_per_m2 = price / surface_m2` uniquement quand les deux sont valides
- Coercition NULL stricte : aucune valeur inventée — les features optionnelles restent vides si non fiables
- Séparation explicite `sale` / `rent` ; les locations sont conservées pour l'analyse mais exclues de l'OBT ML de prix de vente
- Inférence déterministe de `property_type` (`apartment`, `villa`, `studio`, `duplex`, `land`, `office`, `commercial`, etc.) depuis URL, titre, description et attributs

**Validation & Rejet**
- Rejet des lignes sans titre, prix, localisation, URL, surface, date, `batch_id`
- Rejet des prix invalides : `< 1 000` ou `> 100 000 000`
- Nettoyage des features hors plages réalistes :

| Feature | Plage valide |
|---------|-------------|
| `surface_m2` | [10 – 20 000] |
| `chambres` / `salles_de_bain` | [0 – 20] |
| `etage` | [0 – 60] |
| `price_per_m2` | [100 – 100 000] |

**Déduplication**
- Contrainte d'unicité forte sur `listing_url` — une URL = une seule ligne

---

## Framework Qualité des Données

`src/validation/data_quality_checks.py` exécute un ensemble d'assertions systématiques après chaque transformation :

| Contrôle | Assertion |
|----------|-----------|
| Présence des artefacts | Raw CSV, Core Clean CSV et Features CSV existent |
| Plages numériques | Prix, surface et `price_per_m2` dans les plages réalistes |
| Absence de PII | Zéro pattern téléphone/email détecté dans les textes |
| Unicité URL | Zéro doublon sur `listing_url` |
| Champs requis | Colonnes core jamais nulles |
| Cohérence `price_per_m2` | Recalcul de validation via core + features |
| Cohérence BI | `COUNT(fact_listing) = COUNT(clean_listings)` |
| Cohérence ML | `COUNT(ml_property_features) = COUNT(clean_listings)` |
| Intégrité FK | Toutes les clés étrangères du schéma BI résolues |

Chaque exécution produit un rapport JSON auditable :

```json
{
  "batch_id": "batch_20241215_143022",
  "rows_raw": 1247,
  "rows_after_dedup": 1198,
  "rows_clean_core": 1041,
  "rows_dropped_no_price": 87,
  "rows_dropped_no_surface": 54,
  "rows_dropped_duplicate_url": 16,
  "price_per_m2_nulled_out_of_range": 23,
  "surface_nulled_out_of_range": 11,
  "pii_patterns_detected": 0,
  "quality_score": 0.834
}
```

---

## Entrepôt PostgreSQL — Modélisation

### Schémas & Responsabilités

| Schéma | Rôle | Tables principales |
|--------|------|--------------------|
| `staging` | Tampon d'ingestion contrôlé | `raw_listings` |
| `clean` | Source de vérité analytique | `clean_listings`, `clean_listing_features` |
| `bi_schema` | Consommation Power BI | `fact_listing`, `dim_time`, `dim_location` |
| `ml_schema` | Feature store ML | `ml_property_features` |

### Modèle en Étoile — `bi_schema`

```
            dim_time
           ┌─────────────────┐
           │ time_id (PK)    │
           │ scrape_date     │
           │ year · month    │
           │ quarter         │
           └────────┬────────┘
                    │
                    │
dim_location        │             fact_listing
┌─────────────┐     │          ┌────────────────────┐
│ location_id │─────┼──────────│ listing_id (PK)    │
│ city        │     │          │ time_id (FK)       │
│ district    │     └──────────│ location_id (FK)   │
│ region      │                │ price              │
└─────────────┘                │ listing_url        │
                               │ batch_id           │
                               └────────────────────┘
```

Power BI se connecte directement à `bi_schema` : les relations sont préconstruites, les agrégations performantes, les filtres croisés (ville × quartier × période) fonctionnent nativement sans transformation supplémentaire.

### Feature Store ML — `ml_schema`

`ml_property_features` est une table plate construite par jointure de `clean_listings` × `clean_listing_features`. Elle expose directement :

- Variables catégorielles encodables : `city`, `district`, `property_type`
- Variables numériques continues : `price`, `surface_m2`, `price_per_m2`
- Variables discrètes : `chambres`, `salles_de_bain`, `etage`
- Métadonnée temporelle : `scrape_date`, `batch_id`
- Features avancées : `log_price`, `rooms_total`, `price_per_room`, `room_density`, `luxury_flag`, `coastal_city`, `district_market_index`, `city_market_index`, `property_age_bucket`, `surface_x_rooms`, `bathrooms_per_bedroom`
- Contrôle anti-contamination : `ml_property_features` ne contient que les annonces `listing_type = 'sale'`

Aucune transformation supplémentaire n'est requise avant l'entraînement d'un modèle XGBoost ou scikit-learn standard.

---

## Analyse & Business Intelligence

Le schéma en étoile permet des analyses décisionnelles directement depuis Power BI :

| Use Case | Description |
|----------|-------------|
| **Analyse de marché** | Distribution des prix par ville, quartier, type de bien |
| **Suivi temporel** | Évolution du prix au m² entre batches successifs |
| **Benchmark géographique** | `price_per_m2` moyen par zone — identification des opportunités |
| **Détection d'anomalies** | Biens sur/sous-évalués par rapport au marché local |
| **Recherche académique** | Données structurées pour études sur le foncier marocain |

---

## ML Readiness

La table `ml_property_features` est construite pour être directement consommée par un pipeline d'entraînement :

```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql://postgres:password@localhost/avito_db")
df = pd.read_sql("SELECT * FROM ml_schema.ml_property_features", engine)

# Features prêtes — aucun pre-processing supplémentaire requis
X = df[["surface_m2", "chambres", "salles_de_bain", "etage", "city", "district"]]
y = df["price"]
```

**Use cases ML supportés :**
- Prédiction de prix (régression — XGBoost, Random Forest, LightGBM)
- Détection d'anomalies (isolation forest, DBSCAN)
- Segmentation de marché (clustering non supervisé)
- Scoring d'opportunité (biens sous-évalués vs marché)

---

## DevOps & Reproductibilité

Le pipeline s'exécute intégralement en local ou en conteneur Docker avec une seule commande :

```bash
# Démarrer la base de données
docker compose up -d db

# Lancer le pipeline complet (collecte → nettoyage → warehouse)
docker compose run --rm app
```

Toutes les dépendances sont épinglées dans `requirements.txt`. Aucun identifiant n'est hardcodé — toute la configuration passe par variables d'environnement via `.env`.

---

## Structure du Dépôt

```
avito-real-estate-pipeline/
│
├── docker-compose.yml              # Orchestration Docker (app + db)
├── Dockerfile                      # Image applicative Python
├── requirements.txt                # Dépendances épinglées
├── .env.example                    # Template de configuration
│
├── sql/
│   ├── 01_create_staging.sql       # DDL schéma staging
│   ├── 02_create_clean.sql         # DDL schéma clean (core + features)
│   ├── 03_create_bi_schema.sql     # DDL star schema (fait + dimensions)
│   └── 04_create_ml_schema.sql     # DDL feature store ML
│
├── src/
│   ├── extract/
│   │   └── scraper.py              # Collecte éthique Avito.ma
│   ├── staging/
│   │   └── load_staging.py         # Ingestion vers staging
│   ├── clean/
│   │   └── clean_data.py           # Transformation & nettoyage
│   ├── warehouse/
│   │   ├── load_clean.py           # Population schéma clean
│   │   ├── load_bi_schema.py       # Population star schema
│   │   └── load_ml_schema.py       # Population feature store
│   ├── validation/
│   │   └── data_quality_checks.py  # Assertions & rapports qualité
│   ├── orchestration/
│   │   └── run_pipeline.py         # Point d'entrée — orchestration
│   └── utils/                      # Helpers partagés (logging, DB, config)
│
├── data/
│   ├── raw/                        # CSV bruts immuables par batch
│   ├── clean/                      # CSV propres + rapports qualité JSON
│   └── logs/                       # Logs d'exécution pipeline
│
└── tests/                          # Suite pytest (unit + integration)
```

---

## Installation & Démarrage Rapide

**Prérequis** : Python 3.11+, Docker Desktop, Git

```bash
# 1. Cloner le dépôt
git clone https://github.com/<user>/avito-real-estate-pipeline.git
cd avito-real-estate-pipeline

# 2. Environnement virtuel
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .\.venv\Scripts\Activate.ps1    # Windows PowerShell

# 3. Installer les dépendances
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configuration
cp .env.example .env
# Éditer .env avec vos paramètres locaux

# 5. Démarrer PostgreSQL
docker compose up -d db

# 6. Lancer le pipeline
python -m src.orchestration.run_pipeline
```

**Variables d'environnement minimales :**

```env
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=avito_db
DB_USER=postgres
DB_PASSWORD=change_me

SCRAPER_TARGET_LISTINGS=1000
FETCH_DETAIL_PAGES=false
ROBOTS_TXT_MODE=strict
```

---

## Requêtes de Validation

**Contrôle d'intégrité par couche :**

```sql
SELECT
  (SELECT COUNT(*) FROM staging.raw_listings)           AS staging,
  (SELECT COUNT(*) FROM clean.clean_listings)           AS clean,
  (SELECT COUNT(*) FROM bi_schema.fact_listing)         AS bi_fact,
  (SELECT COUNT(*) FROM ml_schema.ml_property_features) AS ml_features;
```

**Statistiques de marché :**

```sql
SELECT
  MIN(price)                        AS prix_min,
  MAX(price)                        AS prix_max,
  ROUND(AVG(price))                 AS prix_moyen,
  ROUND(AVG(f.surface_m2), 1)       AS surface_moyenne_m2,
  ROUND(AVG(f.price_per_m2))        AS prix_m2_moyen
FROM clean.clean_listings c
LEFT JOIN clean.clean_listing_features f ON f.listing_url = c.listing_url;
```

**Benchmark géographique :**

```sql
SELECT
  c.city,
  c.district,
  COUNT(*)                              AS annonces,
  ROUND(AVG(f.price_per_m2), 0)         AS prix_m2_moyen,
  ROUND(PERCENTILE_CONT(0.5)
    WITHIN GROUP (ORDER BY f.price_per_m2), 0) AS prix_m2_median
FROM clean.clean_listings c
LEFT JOIN clean.clean_listing_features f ON f.listing_url = c.listing_url
WHERE f.price_per_m2 IS NOT NULL
GROUP BY c.city, c.district
HAVING COUNT(*) >= 10
ORDER BY annonces DESC;
```

**Distribution par batch (suivi temporel) :**

```sql
SELECT
  batch_id,
  COUNT(*)                      AS annonces,
  ROUND(AVG(f.price_per_m2), 0) AS prix_m2_moyen,
  MIN(c.scrape_date)            AS debut_scraping
FROM clean.clean_listings c
LEFT JOIN clean.clean_listing_features f ON f.listing_url = c.listing_url
GROUP BY batch_id
ORDER BY debut_scraping DESC;
```

---

## Gouvernance & Conformité

Ce pipeline est conçu avec des principes de **Data Governance** dès la collecte :

**Minimisation des données** — Seuls les attributs immobiliers strictement nécessaires à l'analyse sont collectés. Aucune donnée personnelle n'est ingérée, stockée ou transmise à aucune couche du pipeline.

**Séparation des responsabilités** — La couche `staging` isole le brut entrant du reste du warehouse. La couche `clean` est la seule source de vérité consommée en aval.

**Traçabilité complète** — Chaque ligne en base est liée à son `batch_id`. Chaque suppression de ligne est documentée dans le rapport qualité JSON. Chaque exécution est loguée dans `data/logs/pipeline.log`.

**Scraping responsable** — Respect strict de `robots.txt`, délais polis, backoff sur 429, arrêt automatique sur 403. Aucune tentative de contournement de mécanismes de protection.

> Avant toute exécution réelle, vérifier que l'usage est conforme aux conditions d'utilisation d'Avito.ma.

---

## Tests

```bash
python -m pytest
```

La suite couvre : transformations de nettoyage (unit), validations qualité (unit), intégrité référentielle (integration), cohérence des comptages entre couches (integration).

---

## Roadmap

| Priorité | Item |
|----------|------|
| **P1** | Dashboards Power BI connectés à `bi_schema` (modèle en étoile natif) |
| **P1** | CI/CD GitHub Actions (lint, tests, contrôle qualité) |
| **P2** | Orchestration Apache Airflow avec DAG schedulé |
| **P2** | Couche de transformation déclarative dbt |
| **P2** | Validation contractuelle Great Expectations |
| **P3** | Modèle ML de prédiction de prix (XGBoost / scikit-learn) |
| **P3** | API REST FastAPI exposant les données nettoyées |
| **P3** | Monitoring automatisé et alertes qualité |
| **P4** | Déploiement cloud (GCP / AWS) |
| **P4** | Ingestion en streaming (Kafka / Kinesis) |

---

## Compétences Démontrées

| Domaine | Détail |
|---------|--------|
| **Data Engineering** | Pipeline ETL complet · Raw / Staging / Clean / Warehouse · Replayabilité · Traçabilité par batch |
| **Python** | Scraping · Parsing regex · Transformation pandas · CLI · Gestion d'erreurs |
| **PostgreSQL** | Modélisation multi-schémas · Star schema · Intégrité référentielle · Requêtes analytiques |
| **Analytics Engineering** | Modèle en étoile prêt Power BI · Dimensions temps et localisation · Faits mesurables |
| **ML Preparation** | Feature engineering · Table plate · Variables dérivées · Feature store pattern |
| **Data Quality** | Assertions programmatiques · Rapports JSON · Contrôles de cohérence multi-couches |
| **Data Governance** | Scraping éthique · Zéro PII · Minimisation des données · Traçabilité complète |
| **DevOps** | Docker · docker-compose · Environnements reproductibles · Variables d'environnement |
| **Software Design** | Séparation des responsabilités · Couplage faible · Replayabilité · Testabilité |

---

<div align="center">

*Plateforme conçue pour démontrer qu'une ingénierie de données rigoureuse peut produire,*
*même sur un marché émergent, un actif de données structuré, reproductible et décisionnel.*

</div>
