# RAG – mode d'emploi

## 1. Installer le code
```powershell
cd C:\Users\omran\OneDrive\Desktop\projet_pfe\management
Expand-Archive -Path "$HOME\Downloads\rag.zip" -DestinationPath . -Force
pip install -r requirements-dev.txt        # ajoute pgvector et fastembed
python check_files.py                      # doit afficher TOUT EST BON
```
(Ferme tes fichiers ouverts dans VS Code avant l'extraction.)

## 2. Passer ta base sur PostgreSQL + pgvector (Docker)
Ton PostgreSQL local (Windows) n'a pas l'extension **pgvector** : on utilise celui de Docker, qui l'a déjà.
Docker Desktop doit être lancé. Il écoute sur le port **5433** (ton PostgreSQL local reste sur 5432, sans conflit).

**Option A – garder tes données actuelles**
```powershell
$env:PGPASSWORD = "TON_MOT_DE_PASSE_POSTGRES_LOCAL"
pg_dump -U postgres -d meetingai --no-owner -f meetingai.sql        # sauvegarde de ta base locale
docker compose up -d db                                              # base pgvector (mot de passe : "postgres")
docker compose cp meetingai.sql db:/tmp/meetingai.sql
docker compose exec db psql -U postgres -d meetingai -f /tmp/meetingai.sql
```
**Option B – repartir de zéro** (tes réunions de test seront perdues) : `docker compose up -d db`, rien d'autre.

Dans ton `.env` :
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/meetingai
EMBEDDING_CACHE_DIR=C:\Users\omran\.cache\fastembed
```
Puis :
```powershell
alembic upgrade head       # crée l'extension pgvector et la table des passages (migration 0003)
alembic check              # attendu : "No new upgrade operations detected."
```
Si tu es en option B, `alembic upgrade head` suffit aussi. Si Alembic dit que la base n'est pas versionnée,
fais d'abord `alembic stamp 0001`.

## 3. Lancer et indexer
```powershell
uvicorn app.main:app --reload
celery -A app.workers.tasks.celery_app worker --loglevel=info --pool=solo
```
Dans http://localhost:8000/docs : **Authorize**, puis `POST /api/rag/reindex` (indexe tes réunions existantes), puis
`GET /api/rag/status`. Le **premier** lancement télécharge le modèle d'embedding (~220 Mo) : compte une à deux minutes.
Les nouvelles réunions sont indexées automatiquement à la fin de leur traitement.

Essaie ensuite `POST /api/rag/ask` : `{"question": "..."}` sur un sujet réellement évoqué, puis sur un sujet jamais évoqué
(attendu : `answerable: false`, sans source).

## 4. Tests
```powershell
pytest                       # SQLite : 118 tests, les 18 tests RAG sont ignorés (pas de pgvector)
```
Pour exécuter aussi les tests RAG, crée une base `meetingai_test` **dans le PostgreSQL de Docker** :
```powershell
docker compose exec db psql -U postgres -c "CREATE DATABASE meetingai_test;"
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/meetingai_test"
pytest                       # 136 tests
```

## 5. Évaluer (pour obtenir TES chiffres)
Lis `rag_eval/README.md`, écris `rag_eval/qa.json` (20 à 30 questions sur tes vraies réunions, dont ~25 % sans réponse), puis :
```powershell
python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json --no-llm
python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json
```

## 6. Ce qui a été vérifié ici, et ce qui ne l'a pas été
Vérifié (PostgreSQL 16 + pgvector 0.6, versions EXACTES de ton requirements.txt) : 136 tests sur PostgreSQL, 118 sur SQLite ;
migrations (base neuve, base existante, descente) ; scénario réel API + Redis + worker Celery + PostgreSQL de l'upload à la
question avec citations ; ruff.

**NON vérifié** (impossible depuis mon environnement) :
- le **vrai modèle d'embedding** : les tests utilisent un embedding simulé (similarité par mots communs) ; le téléchargement
  de FastEmbed et la **qualité réelle** de la recherche (français, anglais, **arabe**, recherche entre langues) sont inconnus ;
- un vrai LLM pour les réponses (Groq ou Ollama) ;
- le build Docker et la CI GitHub.
Le seuil `RAG_MIN_SIMILARITY=0.25` est une valeur de départ, pas une valeur mesurée : c'est le rôle de l'évaluation.
Ne mets sur ton CV que des chiffres issus de `rag_eval` sur tes propres données.
