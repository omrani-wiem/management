# Guide d'entretien technique — Meeting AI

Ce document est un support de préparation à un entretien. Il décrit le backend présent dans ce dépôt et les choix techniques visibles dans le code. Personnalisez les passages sur votre contribution et vos résultats : ne présentez pas comme mesurée une performance qui n'a pas été évaluée sur un jeu de données.

## 1. Présentation courte du projet

> Meeting AI transforme les enregistrements de réunions en comptes rendus exploitables. L'utilisateur peut envoyer un fichier audio ou utiliser la transcription en direct. Le backend transcrit l'audio avec Whisper, puis utilise un modèle de langage pour produire un résumé, les décisions et les tâches avec leurs responsables, priorités, échéances et repères temporels. Les résultats sont accessibles via une API FastAPI avec authentification JWT et isolation des données par utilisateur. Le projet inclut aussi une recherche RAG sur les réunions passées, avec des réponses sourcées. Les traitements coûteux sont exécutés en arrière-plan avec Celery et Redis.

### Pitch de 30 secondes

> Le problème visé est la difficulté à transformer une réunion en actions concrètes et à retrouver ensuite une information parmi plusieurs comptes rendus. Le système automatise la transcription et l'extraction des décisions et tâches, puis permet de poser des questions en langage naturel avec des citations vers les passages sources. L'architecture sépare l'API, les traitements asynchrones et les données, afin de ne pas bloquer les requêtes pendant les traitements audio et IA.

## 2. Périmètre et technologies

| Composant | Technologie / rôle |
|---|---|
| API backend | Python 3.11, FastAPI, Uvicorn |
| Validation et configuration | Pydantic v2, pydantic-settings |
| ORM et base de données | SQLAlchemy 2, PostgreSQL |
| Recherche vectorielle | pgvector (cosinus, index HNSW) |
| Migrations | Alembic |
| Tâches de fond | Celery avec Redis comme broker et backend |
| Transcription | faster-whisper |
| LLM | Groq ou Ollama, sélection par configuration |
| Embeddings | FastEmbed avec un modèle multilingue par défaut |
| Authentification | JWT HS256 et mots de passe hachés avec bcrypt |
| Tests | pytest, SQLite pour les tests rapides ; certains tests RAG nécessitent PostgreSQL/pgvector |
| Environnement conteneurisé | Docker Compose : API, worker, PostgreSQL/pgvector et Redis |

Le dépôt décrit ici contient le backend et son infrastructure. Le frontend observé pendant le développement est servi séparément à `http://localhost:5173` ; son code source n'est pas présent dans ce dépôt.

## 3. Architecture générale

```text
Navigateur (frontend, localhost:5173)
    │ HTTP / JSON / multipart / WebSocket
    ▼
FastAPI (localhost:8000)
    ├── Authentification et autorisation JWT
    ├── Routes comptes, réunions, tâches, équipes et RAG
    ├── PostgreSQL + pgvector
    └── Redis → Celery worker
                   ├── faster-whisper (audio → transcription)
                   ├── Groq ou Ollama (transcription → compte rendu)
                   └── FastEmbed + pgvector (indexation des passages RAG)
```

La configuration CORS du backend autorise `http://localhost:5173` par défaut. Pour une origine différente, `CORS_ORIGINS` peut contenir une liste d'origines séparées par des virgules.

### Pourquoi séparer API et worker ?

La transcription et les appels aux modèles peuvent être longs et gourmands en ressources. L'API valide la demande, enregistre la réunion, puis place un message dans Redis. Le worker Celery effectue le traitement sans garder la requête HTTP ouverte. L'interface peut consulter le statut de la réunion (`pending`, `processing`, `done` ou `failed`).

## 4. Flux principaux

### 4.1 Traitement d'un fichier audio

1. Le client envoie `POST /api/meetings/upload` avec un titre, un fichier et, éventuellement, les participants et les langues.
2. FastAPI vérifie l'extension, quelques octets de signature du fichier et la taille maximale configurée.
3. Le backend crée un nom de fichier aléatoire côté serveur, enregistre le fichier, puis crée une réunion en statut `pending`.
4. L'identifiant de la réunion est envoyé au worker Celery via Redis.
5. Le worker passe la réunion en `processing`, récupère les noms de référence pertinents, puis transcrit avec faster-whisper.
6. Le texte brut, la langue détectée, la durée et les segments horodatés sont sauvegardés.
7. Le texte, découpé en segments avec des marqueurs temporels, est envoyé au LLM.
8. La sortie JSON du LLM est parsée puis validée par des modèles Pydantic. Si elle est invalide, le code retente jusqu'à trois fois.
9. Le pipeline sauvegarde le résumé, les décisions et les tâches, puis passe la réunion à `done`.
10. Si le RAG est activé, la réunion est indexée au mieux. Un échec d'indexation RAG ne doit pas faire échouer une réunion par ailleurs traitée.

Une transcription sauvegardée est réutilisée si l'étape d'analyse doit être rejouée : cela évite de retranscrire l'audio lorsqu'une erreur ne concerne que le LLM.

### 4.2 Analyse par LLM

Le prompt demande un objet JSON contenant :

- un résumé ;
- les participants détectés ;
- les décisions et leurs éventuels repères temporels ;
- les tâches, descriptions, responsables, niveau de confiance, priorité, échéance et repère temporel.

Les transcriptions longues sont séparées en morceaux. Les résultats sont fusionnés, avec déduplication simple des tâches et décisions. Les sorties ne sont pas prises pour des données fiables sans validation : les champs sont normalisés et typés par Pydantic.

Une tâche dont la confiance d'attribution est inférieure à `0.75` est enregistrée sans responsable. Les échéances restent absentes si le modèle ne peut pas en déduire une de manière suffisamment claire.

### 4.3 Transcription en direct

`/api/live/meeting/{id}` est une route WebSocket. Le client commence par envoyer un message JSON `auth` contenant le JWT et le format audio, puis envoie des blocs audio binaires. Le serveur renvoie des fragments transcrits et finalise le traitement lorsque le client envoie `stop`. L'authentification est effectuée dans le protocole WebSocket plutôt qu'avec le mécanisme HTTP Bearer habituel.

### 4.4 Questions sur les réunions (RAG)

1. À l'indexation, les segments d'une réunion sont regroupés en passages d'environ `RAG_CHUNK_CHARS` caractères. Les passages successifs peuvent partager un segment pour conserver du contexte.
2. Chaque passage est vectorisé par FastEmbed. Le titre de la réunion est inclus dans le texte utilisé pour son embedding.
3. Pour une question, le système effectue une recherche vectorielle par distance cosinus et une recherche PostgreSQL par mots-clés.
4. Les rangs des deux recherches sont fusionnés avec Reciprocal Rank Fusion (RRF).
5. Les requêtes sont restreintes aux réunions appartenant à l'utilisateur authentifié.
6. Si aucun passage ne dépasse le seuil de similarité et qu'aucun résultat ne correspond aux mots-clés, le système refuse la question sans appeler le LLM.
7. Sinon, le LLM reçoit les passages numérotés. La réponse doit être en JSON et citer des sources existantes ; une réponse avec une citation inexistante ou sans citation est rejetée et retentée.

Le RAG réduit le risque de réponse non étayée, mais ne garantit pas l'absence absolue d'hallucination. Les métriques doivent être mesurées avec le jeu de questions de `rag_eval`.

## 5. Modèle de données

| Entité | Contenu / relations |
|---|---|
| `User` | Compte, adresse e-mail, nom, hash de mot de passe |
| `Meeting` | Propriétaire, titre, statut, chemin audio, participants, langues et durée |
| `Transcript` | Texte brut et résumé ; une transcription par réunion |
| `TranscriptSegment` | Texte et positions temporelles de chaque segment |
| `Decision` | Décision extraite et repère temporel source |
| `Task` | Action, responsable, statut, priorité, échéance et repère temporel source |
| `Team` / `TeamMember` | Équipes appartenant à un utilisateur et leurs membres |
| `MeetingChunk` | Passage horodaté, propriétaire et embedding vectoriel utilisé par le RAG |

Les identifiants des principales entités sont des UUID. Les réunions portent l'identifiant de leur propriétaire. Les tâches sont rattachées à une réunion et l'accès aux tâches est filtré en rejoignant la réunion propriétaire.

Les migrations Alembic du projet sont ordonnées : baseline, champs/index de réunions et tâches, passages RAG, liens Jira, puis piste d'audit. En production, les changements de schéma doivent passer par une migration relue et appliquée, plutôt que par la création automatique des tables.

## 6. API à connaître

La documentation interactive générée par FastAPI est disponible sur `http://localhost:8000/docs`.

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Créer un compte |
| `POST` | `/api/auth/login` | Connexion JSON et émission d'un JWT |
| `POST` | `/api/auth/token` | Connexion formulaire OAuth2, notamment pour Swagger |
| `GET` | `/api/auth/me` | Lire le compte connecté |
| `POST` | `/api/meetings/upload` | Envoyer un fichier audio pour traitement asynchrone |
| `POST` | `/api/meetings/create` | Créer une réunion destinée au mode live |
| `GET` | `/api/meetings/` | Lister les réunions du compte connecté |
| `GET` | `/api/meetings/{id}` | Lire le détail, la transcription et les décisions |
| `GET` | `/api/meetings/{id}/segments` | Lire les segments horodatés |
| `GET`, `PATCH` | `/api/tasks/`, `/api/tasks/{id}` | Filtrer et mettre à jour les tâches |
| `GET` | `/api/audit/` | Lire l'historique paginé des appels API authentifiés du compte |
| `GET`, `POST` | `/api/team/...` | Gérer équipes et membres |
| `GET` | `/api/team/members` | Membres et charge de travail |
| `POST` | `/api/rag/ask` | Poser une question et obtenir une réponse sourcée |
| `POST` | `/api/rag/search` | Rechercher des passages sans appeler le LLM |
| `GET` | `/api/rag/status` | État de l'index RAG de l'utilisateur |
| `POST` | `/api/rag/reindex` | Mettre en file la réindexation des réunions terminées |
| `WS` | `/api/live/meeting/{id}` | Transcription audio en direct |
| `GET` | `/health`, `/health/ready` | Liveness et vérification de la base/Redis |

Les routes métier, sauf les routes publiques d'inscription, de connexion et de santé, exigent un JWT Bearer. Une réunion d'un autre propriétaire doit être inaccessible, même si son UUID est connu.

## 7. Sécurité et fiabilité

- **Mots de passe** : stockage sous forme de hash bcrypt, jamais en clair.
- **JWT** : signature HS256 et expiration par défaut après 24 heures ; les routes valident le jeton avant de retrouver l'utilisateur.
- **Isolation des données** : les listes et accès aux réunions, tâches, équipes et passages RAG sont limités à l'utilisateur courant.
- **Fichiers** : nom de fichier généré côté serveur ; validation extension/signature ; limite de taille configurable.
- **CORS** : autorisation explicite des origines configurées ; ne pas utiliser une origine wildcard en production avec des cookies/credentials.
- **Traitements** : le worker marque les réunions en échec et journalise les exceptions. Celery retente les erreurs transitoires du traitement de réunion.
- **Migrations** : Alembic assure l'évolution contrôlée du schéma.
- **Secrets** : les clés API et secrets restent dans `.env` ou l'environnement de déploiement, jamais dans le dépôt ou dans ce guide.
- **RAG** : sources explicitement numérotées, validation des citations et filtrage utilisateur. Les extraits de transcription sont traités comme des données non fiables dans le prompt.
- **Masquage à l'envoi** : e-mails, téléphones, IBAN valides (contrôle modulo 97) et numéros de carte valides (Luhn) sont remplacés avant les appels LLM et l'envoi de tâches à Jira. Les réponses des LLM sont également filtrées.
- **Traçabilité** : les appels HTTP API authentifiés sont inscrits dans `audit_events` avec utilisateur, méthode, modèle de route, identifiant de ressource, statut HTTP, date et identifiant de requête. `X-Request-ID` permet de retrouver la requête ; les corps et contenus de réunion ne sont pas copiés dans la piste d'audit.

### Limites à reconnaître honnêtement

- La limitation des tentatives de connexion est en mémoire et par processus ; plusieurs instances ne partagent donc pas le compteur.
- L'attribution, les échéances et la qualité du résumé dépendent de l'audio, de la transcription et du modèle. L'humain doit pouvoir vérifier les résultats.
- L'index vectoriel exige PostgreSQL avec pgvector. Une modification de dimension d'embedding nécessite une migration et une réindexation.
- Le modèle d'embedding peut devoir être téléchargé au premier usage et est mis en cache.
- Les tests qui exigent pgvector ne sont pas couverts par le jeu rapide SQLite.
- Les appels Groq envoient le contenu nécessaire à l'analyse à un service distant ; Ollama peut être utilisé pour une exécution locale, sous réserve d'avoir téléchargé le modèle local.
- Le masquage protège les envois aux fournisseurs LLM et à Jira, mais ne nettoie pas les transcriptions/audio conservés en base et dans `uploads/`, ni les réponses affichées aux utilisateurs. Il ne constitue pas un chiffrement au repos.
- La piste d'audit ne possède pas encore de politique automatique de purge : la durée de conservation, la suppression et les sauvegardes doivent être définies avant un déploiement en production.
- Le seuil RAG par défaut est une valeur de départ, pas une performance démontrée. Il doit être calibré avec des données représentatives.
- Les identifiants de modèles hébergés peuvent changer ou être retirés. Le choix du fournisseur et du modèle est configurable ; en cas d'erreur, consulter les journaux du worker et la documentation du fournisseur.

## 8. Lancer le projet

### Recommandé : Docker Compose

Prérequis : Docker Desktop démarré et un fichier `.env` configuré avec les paramètres requis. Ne partagez pas ce fichier, car il contient des secrets.

Depuis PowerShell :

```powershell
cd C:\Users\omran\OneDrive\Desktop\projet_pfe\management
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 api worker
```

L'API est sur `http://localhost:8000`, Swagger sur `/docs`, PostgreSQL est exposé sur le port `5433`, et Redis est utilisé par l'application. L'API Compose applique les migrations au démarrage. `docker compose ps` doit montrer l'API saine et le worker démarré.

Vérifier les services :

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/health/ready
```

Le endpoint `/health` vérifie que le processus API répond. `/health/ready` vérifie la base de données et signale Redis. Une réponse `503` sur le second indique que l'API ne peut pas utiliser la base, même si `/health` répond.

Pour arrêter les conteneurs sans supprimer les données persistées :

```powershell
docker compose down
```

### Variante sans Docker

Le README donne la procédure Windows/Linux : Python 3.11, PostgreSQL avec pgvector, Redis, environnement virtuel, dépendances et migration Alembic. Il faut démarrer l'API et le worker dans deux terminaux. Sous Windows, le worker Celery utilise `--pool=solo`.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Dans un second terminal :

```powershell
.\venv\Scripts\Activate.ps1
celery -A app.workers.tasks.celery_app worker --loglevel=info --pool=solo
```

Les valeurs de `DATABASE_URL` et `REDIS_URL` doivent alors viser les services accessibles depuis la machine hôte. Pour les détails, consulter la section démarrage du `README.md`.

## 9. Configuration importante

La configuration est chargée par `pydantic-settings` depuis l'environnement et `.env`. Le fichier `.env.example` sert de modèle, pas de fichier de secrets.

| Variable | Usage |
|---|---|
| `DATABASE_URL` | Connexion PostgreSQL |
| `REDIS_URL` | Broker/backend Celery |
| `SECRET_KEY` | Signature JWT ; utiliser une valeur longue et aléatoire |
| `LLM_PROVIDER` | `groq` ou `ollama` |
| `GROQ_API_KEY` | Clé Groq, si le fournisseur choisi est Groq |
| `GROQ_MODEL` | Identifiant du modèle Groq |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Adresse et modèle local Ollama |
| `WHISPER_MODEL` | Taille/modèle de transcription |
| `WHISPER_LANGUAGE` | Langue explicite ou détection automatique |
| `CORS_ORIGINS` | Origines frontend autorisées, séparées par virgules |
| `MAX_UPLOAD_MB` | Taille maximale d'un fichier audio |
| `RAG_ENABLED` | Activer ou non les fonctionnalités RAG |
| `EMBEDDING_MODEL` | Modèle de vecteurs |
| `RAG_CHUNK_CHARS`, `RAG_TOP_K`, `RAG_MIN_SIMILARITY` | Paramètres de découpage, recherche et filtrage |
| `AUTO_CREATE_TABLES` | Création automatique réservée au développement ; préférer Alembic |

Ne pas mettre une vraie clé API dans une présentation, un commit, un ticket public ou une capture d'écran.

## 10. Tests et validation

Le projet utilise pytest. Les tests rapides sont configurés pour fonctionner avec SQLite temporaire ; les tests qui dépendent réellement de pgvector/PostgreSQL doivent être exécutés séparément sur une base de test.

```powershell
pip install -r requirements-dev.txt
pytest
ruff check app tests alembic rag_eval
```

Les appels au LLM, Whisper et Celery sont simulés dans les tests où cela est pertinent : les tests unitaires ne doivent pas nécessiter un appel payant au fournisseur ni un vrai traitement audio. Les tests PostgreSQL refusent une base dont le nom ne se termine pas par `_test`, afin de limiter le risque de toucher une base de développement.

Principaux domaines couverts par les fichiers de tests :

- authentification et autorisation ;
- isolation des données entre utilisateurs ;
- réunions et validation des fichiers ;
- tâches et équipes ;
- pipeline de sauvegarde, analyse LLM et gestion live ;
- composants RAG et son évaluation ;
- intégration pgvector/PostgreSQL, dans une suite dédiée.

Pour le RAG, `python -m rag_eval` évalue une collection de questions/réponses. Le jeu doit comporter des questions répondables et non répondables ; les chiffres de `hit@k`, MRR, refus corrects, faux refus et précision des citations ne doivent être annoncés qu'après avoir réellement exécuté l'évaluation.

## 11. Questions d'entretien probables

### « Pourquoi utiliser FastAPI ? »

FastAPI permet de construire rapidement des routes typées, de valider les entrées/sorties avec Pydantic et de générer OpenAPI/Swagger automatiquement. Il prend également en charge les WebSockets, utiles pour la transcription live.

### « Pourquoi Celery/Redis ? »

Une requête d'upload ne doit pas rester ouverte pendant la transcription et l'analyse. Celery exécute les travaux asynchrones et Redis transporte les messages. La réunion conserve un statut consultable par l'interface. Pour un déploiement plus robuste, on peut ajouter suivi des tâches, métriques, politiques de retry adaptées et supervision du worker.

### « Comment gérez-vous les erreurs du LLM ? »

La sortie structurée est analysée puis validée par Pydantic. Une réponse mal formée est retentée jusqu'à trois fois. Les exceptions du traitement sont journalisées ; Celery retente le travail et la réunion finit en statut `failed` après épuisement des tentatives. La transcription déjà enregistrée est réutilisée afin de ne pas refaire le travail Whisper lorsqu'il n'est pas nécessaire.

### « Comment limitez-vous les hallucinations ? »

Le prompt demande de ne pas inventer et de ne s'appuyer que sur la transcription. Les objets JSON sont validés et les responsabilités peu fiables sont laissées sans assignation. Pour le RAG, la recherche doit fournir des passages pertinents et chaque réponse affirmative doit citer des sources existantes. Cela améliore la traçabilité sans prouver que chaque affirmation est vraie : une validation humaine et une évaluation restent nécessaires.

### « Comment garantissez-vous l'isolation des utilisateurs ? »

Le JWT identifie l'utilisateur courant. Les requêtes réunion/équipe filtrent par propriétaire ; les tâches rejoignent les réunions pour appliquer le même filtre ; les passages RAG sont filtrés avec `owner_id`. Les tests d'isolation vérifient qu'un utilisateur ne récupère pas les données d'un autre.

### « Pourquoi recherche hybride dans le RAG ? »

Les embeddings retrouvent des formulations sémantiquement proches même si les mots diffèrent. La recherche par mots-clés est meilleure pour les noms propres, références ou chiffres. RRF combine les rangs sans devoir comparer directement des scores de nature différente.

### « Comment évitez-vous une migration destructive ? »

Les changements de schéma sont versionnés avec Alembic. On génère ou écrit une migration, on la relit, puis on l'applique avec `alembic upgrade head`. En production, on évite de compter sur `create_all`.

### « Que signifie une erreur 401 ? Et une 400 à l'inscription ? »

Une `401` sur une route protégée signifie que le jeton Bearer est absent, invalide ou expiré. Il faut se reconnecter et envoyer le jeton. Une `400` d'inscription peut signifier que l'adresse est déjà utilisée ; le détail de réponse HTTP précise le cas. Une erreur `400` n'est pas nécessairement une erreur CORS.

### « Que signifie une réunion en échec ? »

Le statut seul ne donne pas la cause. Il faut corréler l'identifiant de réunion et l'heure avec les logs du worker, car transcription, appel fournisseur, analyse JSON ou indexation peuvent échouer différemment. Dans l'incident observé pendant le développement, le worker signalait que `llama-3.3-70b-versatile` n'était plus disponible chez Groq. Le modèle configuré a été remplacé par `openai/gpt-oss-120b`, et les services API/worker ont été reconstruits. Il faut toujours vérifier le modèle et les droits disponibles auprès du fournisseur au moment du déploiement.

### « Quelles améliorations envisageriez-vous ? »

Réponses possibles, à adapter à vos priorités :

1. Remplacer la limitation de connexion en mémoire par un stockage partagé et ajouter une politique distribuée.
2. Ajouter observabilité structurée : métriques de durée par étape, nombre de retries, erreurs par fournisseur, longueur des files Celery.
3. Mesurer la qualité Whisper et RAG sur des jeux représentatifs en français, anglais et arabe.
4. Ajouter des mécanismes de reprise/réessai explicites pour les réunions échouées et les rendre visibles à l'utilisateur.
5. Renforcer la gestion des fichiers (durée maximale, quotas, politique de rétention/suppression, stockage objet en production).
6. Ajouter des tests d'intégration et de charge sur l'ensemble API → Redis → worker → base.
7. Évaluer le coût, la latence et la confidentialité des fournisseurs LLM selon les besoins.

## 12. Démonstration conseillée en entretien

1. Montrer `/docs` et expliquer l'authentification.
2. Créer un compte de démonstration ou se connecter, puis montrer le jeton sans le copier dans des captures.
3. Envoyer un petit audio de test, puis montrer l'évolution du statut de la réunion.
4. Afficher la transcription, son résumé, une décision et une tâche avec un repère temporel.
5. Poser une question sur une information explicitement présente et montrer les sources citées.
6. Poser une question absente des réunions et montrer le refus, sans présenter celui-ci comme une garantie absolue.
7. Expliquer comment consulter les logs API/worker et comment lancer les tests.

Utiliser uniquement des enregistrements autorisés et des données de démonstration non sensibles.

## 13. Points à compléter avant l'entretien

- Ma contribution personnelle : `[décrire précisément les modules/fonctionnalités réalisés par vous]`.
- Une difficulté technique réelle et sa résolution : `[contexte → diagnostic → changement → résultat vérifié]`.
- Une décision d'architecture dont vous êtes responsable : `[choix et alternatives considérées]`.
- Résultats de tests : `[commande exécutée et résultat réel]`.
- Résultats de l'évaluation RAG : `[jeu utilisé, taille, métriques mesurées ; laisser vide si non mesuré]`.
- Limites connues : choisir deux ou trois limites pertinentes et expliquer comment vous les prioriseriez.

Ne prétendez pas avoir entraîné Whisper ou le LLM : dans ce projet, Whisper et les modèles de langage sont utilisés comme composants externes/pré-entraînés. La valeur du projet est notamment dans le pipeline, l'intégration, la validation, la traçabilité, l'isolation des données et l'expérience de recherche.

## 14. Fichiers importants à relire

- `app/main.py` : création de l'application, CORS et inclusion des routes.
- `app/config.py` : paramètres de l'application.
- `app/routers/meetings.py` : upload, création et lecture des réunions.
- `app/routers/auth.py`, `app/auth_utils.py` : connexion, mots de passe et JWT.
- `app/workers/tasks.py` : tâches Celery et pipeline de réunion.
- `app/services/transcription.py` : transcription faster-whisper.
- `app/services/ai_processor.py` : prompts, découpage et validation des résultats LLM.
- `app/services/meeting_pipeline.py` : persistance commune des transcriptions, tâches et décisions.
- `app/services/llm_provider.py` : adaptateurs Groq et Ollama.
- `app/services/rag.py`, `app/routers/rag.py` : indexation, recherche et réponses sourcées.
- `app/models/` et `alembic/versions/` : modèle relationnel et migrations.
- `docker-compose.yml`, `Dockerfile`, `README.md` : lancement et déploiement local.
- `tests/` et `rag_eval/` : validation et évaluation.
