# Templates de formulaires

## Vue d'ensemble

DoctorFill supporte 3 types de formulaires médicaux suisses. Chaque template est défini dans un fichier JSON qui mappe les champs du formulaire aux chemins XML/XFA du PDF.

## Structure d'un template

```json
{
  "id": "1.1",
  "question": "Quel est le nom de famille du patient ?",
  "xml_path": "Seite1.nom_patient"
}
```

| Champ | Description |
|-------|-------------|
| `id` | Identifiant unique du champ dans le formulaire |
| `question` | Question envoyée au LLM pour l'extraction |
| `xml_path` | Chemin dans l'arbre XML/XFA du PDF |

## Templates disponibles

### Form_AVS — Assurance vieillesse et survivants

- **Fichier** : `template/Form_AVS.json`
- **Champs** : ~100
- **Sections** :
  1. Canton de traitement
  2. Données du patient (nom, prénom, adresse, AVS, etc.)
  3. Détails de traitement (7 périodes)
  4. Informations médicales (symptômes, diagnostic, médicaments, pronostic)
  5. Activité professionnelle et restrictions
  6. Horaires de travail et pronostic d'intégration
  7. Informations complémentaires et coordonnées du médecin

### Form_Cardio — Formulaire de cardiologie

- **Fichier** : `template/Form_Cardio.json`
- **Champs** : ~60
- **Sections** :
  - Données patient et assurance
  - Contact médecin
  - Raison du traitement et rendez-vous
  - Examens (ECG, tests d'effort, échocardiographie, pacemaker)
  - Anamnèse et notes médicales
  - Contact spécialiste et médecin traitant

### Form_LAA_ABRG — Accident (loi fédérale)

- **Fichier** : `template/Form_LAA_ABRG.json`
- **Champs** : ~23
- **Sections** :
  - Numéro d'accident et données patient
  - Dates de traitement et incapacité
  - Coordonnées du médecin et certification

## Bonnes pratiques pour les questions

### À faire

- Rédiger des questions complètes et spécifiques
- Inclure le contexte de l'entité ("du patient", "du médecin")
- Être précis sur le type de donnée attendu

```json
{
  "question": "Quel est le numéro de téléphone du patient ?"
}
```

### À éviter

- Questions trop courtes (1-2 mots) → mauvais retrieval
- Questions ambiguës (sans contexte d'entité)

```json
{
  "question": "Téléphone"
}
```

## Problèmes connus

| Template | Problème | Issue |
|----------|----------|-------|
| AVS | ID 3.29 dupliqué | #22 |
| AVS | Champ 1.1 "Ne répond rien" | #24 |
| LAA | ID 4.1 utilisé 3 fois | #22 |
| Cardio | Questions trop courtes | #23 |
| LAA | Questions trop courtes | #23 |
