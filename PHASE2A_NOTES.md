# Phase 2a – mode d'emploi

## 0. Correction d'une régression de la Phase 1
`GET /api/meetings/{id}` ne renvoyait plus `summary` ni `raw_text`. C'est corrigé (et testé).

## 1. Installer
```powershell
cd C:\Users\omran\OneDrive\Desktop\projet_pfe\management
Expand-Archive -Path "$HOME\Downloads\phase2a.zip" -DestinationPath . -Force
pip install -r requirements.txt        # ajoute httpx
python check_files.py                  # doit afficher TOUT EST BON
```
Ferme dans VS Code les fichiers ouverts avant d'extraire (sinon Windows peut refuser d'en écraser un).

## 2. Migration SQL (nouvelles colonnes ; les nouvelles TABLES sont créées toutes seules au démarrage)
```sql
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS language VARCHAR(10);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS output_language VARCHAR(10);
ALTER TABLE tasks    ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE tasks    ADD COLUMN IF NOT EXISTS source_seconds INTEGER;
```
(`psql -U postgres -d meetingai`)

## 3. Tester sans rien installer d'autre
```powershell
python smoke_test.py      # 37 vérifications, tout est simulé, ta base n'est pas touchée
```
Puis lance uvicorn + celery comme avant. Les anciennes réunions n'ont pas de décisions ni de segments :
c'est normal, il faut en retraiter une nouvelle.

## 4. Nouveautés
| Quoi | Où |
|---|---|
| Décisions extraites (avec raison + horodatage) | `GET /api/meetings/{id}` -> champ `decisions` |
| Transcription horodatée | `GET /api/meetings/{id}/segments` |
| Langue parlée | upload : champ `language` = `auto` (défaut) / `fr` / `en` / `ar` |
| Langue du résumé, décisions, tâches | upload : champ `output_language` = `fr` / `en` / `ar` (défaut : langue parlée, sinon `fr`) |
| Échéances des tâches | `due_date` + `source_seconds` dans `TaskOut`, `PATCH` accepte `due_date` |
| Filtres tâches | `GET /api/tasks/?status=todo&assignee=Ali&overdue=true` |
| LLM interchangeable | `.env` : `LLM_PROVIDER=groq` ou `ollama` |

### LLM local (Ollama)
```
ollama pull qwen2.5:7b
```
`.env` : `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:7b`. Plus aucune donnée ne quitte la machine.

### Arabe
Le modèle Whisper `base` est faible en arabe : mets `WHISPER_MODEL=small` (ou `medium` si ton PC suit).
Le premier lancement télécharge le modèle.

## 5. Changements côté front (à garder pour quand tu m'envoies le front)
- Upload / création live : nouveaux champs optionnels `language`, `output_language`.
- Détail réunion : afficher `decisions` (avec `source_seconds` = moment dans la réunion), `language`.
- Tâches : afficher `due_date`, filtres, badge « en retard ».
- Message WebSocket `done` : nouveaux champs `decisions`, `language`, `output_language` ; chaque tâche a `due_date` et `timestamp`.

## 6. Limites connues (honnêtes)
- Les horodatages des décisions/tâches sont donnés par le LLM à partir des marqueurs [mm:ss] : à vérifier sur de vrais audios.
- Détection de langue en live : par morceau de ~8 s, moins fiable que sur un fichier entier. Choisis la langue à la création si tu la connais.
- La qualité en arabe dépend du modèle Whisper ET du LLM : à tester avec un vrai audio avant de l'écrire sur ton CV.
