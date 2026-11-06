# Meeting AI : backend

API de **comptes rendus de réunion assistés par IA**. On envoie un enregistrement (ou on parle en direct) ; l'application
produit la transcription horodatée, un résumé, les **décisions** prises et les **tâches** à faire (responsable, priorité,
échéance), en **français, anglais ou arabe**.

## Fonctionnalités

- Upload audio (`mp3 wav m4a mp4 webm ogg`) ou **transcription en direct** par WebSocket
- Transcription avec **faster-whisper**, détection automatique de la langue, segments horodatés
- Analyse par LLM interchangeable : **Groq** (cloud) ou **Ollama** (local, aucune donnée ne quitte la machine)
- Sortie JSON **validée** (Pydantic), avec nouvelle tentative si le LLM répond mal
- Horodatage des décisions et des tâches dans la réunion ; échéances résolues à partir de la date de la réunion
- Traitement asynchrone (**Celery + Redis**), reprise sans retranscrire si l'analyse échoue
- Authentification JWT, **isolation stricte des données** entre utilisateurs, limitation des tentatives de connexion
- Équipes, membres et charge de travail par membre
- **RAG** : poser une question sur toutes ses réunions passées et obtenir une réponse **avec citations** (réunion, minute, extrait) ; recherche hybride (vecteurs pgvector + mots-clés PostgreSQL) ; refus explicite quand l'information n'existe pas ; module d'**évaluation chiffrée** (`rag_eval`)
- **Masquage PII** (e-mails, téléphones, IBAN valides, cartes valides) avant envoi au LLM/Jira, et **piste d'audit** des appels API authentifiés sans corps de requête
- Migrations **Alembic**, tests **pytest** (SQLite ou PostgreSQL), CI GitHub Actions, Docker Compose

## Architecture

```mermaid
flowchart LR
  C[Client web] -->|HTTP| A[API FastAPI]
  C -. WebSocket .-> A
  A --> P[(PostgreSQL)]
  A -->|file de tâches| R[(Redis)]
  R --> W[Worker Celery]
  W --> T[faster-whisper]
  W --> L[LLM : Groq ou Ollama]
  W --> P
  W --> E[FastEmbed : embeddings]
  A -->|question| E
```

Flux d'un upload : `POST /api/meetings/upload` → fichier enregistré, réunion `pending` → tâche Celery →
transcription et segments sauvegardés → analyse LLM → décisions, tâches et résumé sauvegardés → réunion `done`.

## RAG : interroger ses réunions

```http
POST /api/rag/ask
{"question": "Qui doit envoyer le devis au client ?"}
```
```json
{"answer": "Ali enverra le devis avant vendredi [1].", "answerable": true,
 "sources": [{"ref": 1, "meeting_title": "Sprint backend", "timestamp": "00:20", "text": "Ali enverra le devis au client avant vendredi.", "similarity": 0.67}]}
```

Fonctionnement : les réunions sont découpées en passages horodatés (~700 caractères), vectorisés avec un modèle **multilingue** (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions) et stockés dans **pgvector**. À chaque question, une recherche vectorielle (cosinus, index HNSW) et une recherche par mots-clés (utile pour les noms propres, références, chiffres) sont fusionnées par **RRF**, toujours restreintes aux réunions de l'utilisateur. Le LLM ne reçoit que les passages retenus et doit **citer ses sources** : une réponse sans citation valide est rejetée et relancée, et si aucun passage n'est pertinent la question est refusée **sans appel au LLM**.

| Route | Rôle |
|---|---|
| `POST /api/rag/ask` | question → réponse avec citations (`meeting_id` optionnel pour cibler une réunion) |
| `POST /api/rag/search` | recherche seule, sans LLM (passages + similarité) |
| `GET /api/rag/status` | réunions indexées, nombre de passages |
| `POST /api/rag/reindex` | (ré)indexe toutes les réunions terminées, à lancer une fois pour l'existant |

L'**évaluation** (hit@k, MRR, taux de refus à bon escient…) se lance avec `python -m rag_eval` : voir `rag_eval/README.md`.

## Démarrage rapide avec Docker

```bash
cp .env.example .env        # puis renseigne GROQ_API_KEY et SECRET_KEY
docker compose up --build
```
API : http://localhost:8000 · documentation interactive : http://localhost:8000/docs.
Les migrations s'appliquent automatiquement. Au premier traitement, le modèle Whisper est téléchargé (volume `models`).

LLM local : `docker compose --profile local-llm up --build`, puis
`docker compose exec ollama ollama pull qwen2.5:7b` et `LLM_PROVIDER=ollama` dans `.env`.

## Démarrage sans Docker (Windows / Linux)

Prérequis : Python 3.11, PostgreSQL, Redis.

```bash
python -m venv venv && venv\Scripts\activate         # Linux : source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                  # puis édite .env
alembic upgrade head                                  # crée les tables
uvicorn app.main:app --reload                         # terminal 1
celery -A app.workers.tasks.celery_app worker --loglevel=info --pool=solo   # terminal 2 (--pool=solo sous Windows)
```

## Migrations de base de données

| Situation | Commande |
|---|---|
| Base neuve | `alembic upgrade head` |
| Base **créée avant Alembic** (ancien `create_all`) | `alembic stamp 0001` puis `alembic upgrade head` |
| Après avoir modifié un modèle | `alembic revision --autogenerate -m "description"` puis relire le fichier généré et `alembic upgrade head` |
| Vérifier que les modèles et la base concordent | `alembic check` |

## Tests

```bash
pip install -r requirements-dev.txt
pytest                      # SQLite temporaire : rapide, aucun service requis (les tests RAG, qui exigent pgvector, sont ignorés)
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/meetingai_test pytest   # sur PostgreSQL
ruff check app tests alembic rag_eval
```

Whisper, le LLM et Celery sont simulés dans les tests. Les tests ne touchent jamais à ta base de développement : ils refusent
toute base PostgreSQL dont le nom ne finit pas par `_test`.

## API (résumé)

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | inscription, connexion (JWT) |
| POST | `/api/meetings/upload` | envoyer un audio (`title`, `file`, `participants`, `language`, `output_language`) |
| POST | `/api/meetings/create` | créer une réunion pour le mode live |
| GET | `/api/meetings/`, `/api/meetings/{id}` | liste paginée, détail (résumé, transcription, décisions) |
| GET | `/api/meetings/{id}/segments` | transcription horodatée |
| GET / PATCH | `/api/tasks/`, `/api/tasks/{id}` | tâches (filtres `status`, `assignee`, `overdue`) |
| POST | `/api/tasks/{id}/jira` | créer un ticket Jira pour une tâche (si l'intégration est configurée) |
| POST | `/api/tasks/{id}/jira/refresh` | actualiser le statut du ticket Jira lié |
| GET | `/api/audit/` | historique paginé des appels API de l'utilisateur connecté (filtres `skip`, `limit`) |
| * | `/api/team/...` | équipes, membres, `GET /api/team/members` (charge de travail) |
| WS | `/api/live/meeting/{id}` | transcription en direct |
| GET | `/health`, `/health/ready` | état du service, de la base et de Redis |

Toutes les routes, sauf inscription, connexion et `/health*`, exigent `Authorization: Bearer <token>`.

## Configuration

Voir `.env.example`. Variables principales : `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `LLM_PROVIDER` (`groq` ou `ollama`),
`GROQ_API_KEY`, `OLLAMA_MODEL`, `WHISPER_MODEL` (au moins `small` pour l'arabe), `CORS_ORIGINS`, `MAX_UPLOAD_MB`.

### Jira Cloud

L'intégration est facultative et utilise un compte Jira Cloud commun au serveur. Configure `JIRA_BASE_URL`
(URL HTTPS du site, par exemple `https://mon-espace.atlassian.net`), `JIRA_EMAIL`, `JIRA_API_TOKEN`
(jeton API Atlassian) et `JIRA_PROJECT_KEY` dans `.env`. Applique ensuite `alembic upgrade head`.
Pour une tâche extraite, appelle `POST /api/tasks/{id}/jira` afin de créer son ticket. La réponse de tâche
contient la clé et l'URL Jira. `POST /api/tasks/{id}/jira/refresh` actualise ensuite `jira_status` depuis Jira.
La création est manuelle et une tâche ne peut être liée qu'à un seul ticket. Les identifiants restent côté
serveur ; l'API token doit être conservé dans un gestionnaire de secrets en production.

### Masquage et piste d'audit

Avant chaque appel aux fournisseurs LLM (Groq ou Ollama), les e-mails, numéros de téléphone, IBAN dont la
clé de contrôle est valide et numéros de carte passant Luhn sont remplacés par des marqueurs. Le même
masquage est appliqué aux titres et descriptions envoyés à Jira et aux réponses des LLM avant leur traitement.
La piste d'audit (`GET /api/audit/`) consigne pour chaque requête HTTP API authentifiée l'utilisateur, la méthode,
le modèle de route, l'identifiant de ressource UUID, le code HTTP, un identifiant de requête et la date.
Elle ne stocke ni les corps de requête/réponse, ni les transcriptions, ni les jetons d'authentification.

**Limite importante :** ce masquage protège les envois aux services LLM et Jira, mais ne modifie pas les
transcriptions/audio déjà conservés dans PostgreSQL et `uploads/`, ni les données affichées à l'utilisateur.
Il ne remplace pas le chiffrement au repos, les contrôles d'accès, la gestion des sauvegardes ni une politique
de conservation/suppression des fichiers et journaux. Les événements d'audit n'ont pas encore de suppression
automatique ; définis une durée de conservation adaptée avant un déploiement en production.

## Limites connues et suite

- La qualité de l'arabe dépend du modèle Whisper et du LLM choisis : à évaluer sur des enregistrements réels.
- L'horodatage des décisions et des tâches est proposé par le LLM à partir des marqueurs `[mm:ss]` : à vérifier.
- La limitation des connexions est en mémoire, par processus (non partagée entre plusieurs instances).
- Le RAG demande PostgreSQL avec l'extension **pgvector** (fournie par l'image Docker `pgvector/pgvector`). Changer de modèle d'embedding de dimension différente demande une migration et une réindexation.
- Le seuil `RAG_MIN_SIMILARITY` (0,25) est une valeur de départ : à calibrer avec `rag_eval` sur tes propres réunions.
- Avec Groq, les passages retrouvés sont envoyés au service cloud pour générer la réponse ; avec Ollama, rien ne quitte la machine.
- **À venir** : suivi des actions d'une réunion à l'autre, réponses en flux (streaming).
