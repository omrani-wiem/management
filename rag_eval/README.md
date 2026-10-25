# Évaluer le RAG sur tes réunions

Les chiffres que tu mettras sur ton CV doivent venir de **tes** données. Ce dossier sert à les produire.

## 1. Écrire le jeu de questions (`rag_eval/qa.json`)
Prends 5 à 10 réunions déjà traitées et écris **au moins 20 questions** (idéalement 30) :
- ~75 % de questions **avec réponse** dans les réunions ;
- ~25 % de questions **sans réponse** (sujet jamais abordé) : on mesure si le système refuse au lieu d'inventer ;
- si possible quelques questions en arabe ou en anglais sur des réunions en français (recherche multilingue).

Format (voir `qa.example.json`) :

| Champ | Rôle |
|---|---|
| `question` | la question posée |
| `answerable` | `true` si la réponse est dans les réunions, `false` sinon |
| `evidence` | une ou plusieurs **phrases exactes** de la transcription, qui contiennent la réponse (copie-les depuis `GET /api/meetings/{id}`, champ `raw_text`) |
| `answer_keywords` | (optionnel) mots qui doivent figurer dans la réponse, ex. un nom, un montant |
| `meeting_title` | (optionnel) le bon passage doit venir de cette réunion |

Écris les questions **avec tes mots**, pas en recopiant la transcription, sinon la recherche paraît meilleure qu'elle ne l'est.

## 2. Lancer
```bash
python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json --no-llm   # recherche seule, sans LLM
python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json            # recherche + réponses
```

## 3. Ce que mesurent les chiffres
- **hit@k** : part des questions dont un passage pertinent figure parmi les k premiers résultats.
- **mrr** : 1 / rang du premier passage pertinent, en moyenne (1,0 = toujours en première position).
- **correct_refusal_rate** : sur les questions sans réponse, part où le système refuse au lieu d'inventer.
- **false_refusal_rate** : sur les questions avec réponse, part où il refuse à tort.
- **keyword_accuracy** : part des réponses contenant les mots attendus.
- **citation_precision** : part des sources citées qui contiennent bien la preuve.
- La validité des citations (numéros qui existent) est garantie par construction : une réponse sans citation valide est rejetée.

## 4. Régler
Si `hit@5` est bas : essaie `RAG_CHUNK_CHARS` (400 à 1000) ou un modèle d'embedding plus grand.
Si le système invente ou refuse trop : ajuste `RAG_MIN_SIMILARITY` (0,20 à 0,40). Relance et compare les rapports (`rag_eval/reports/`).
Sur le CV, cite le **nombre de questions**, le modèle et les métriques, sans arrondir en ta faveur.
