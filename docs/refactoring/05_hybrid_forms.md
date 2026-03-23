# 05 — Support des Formulaires Hybrides (XFA + AcroForm)

## Contexte

Les formulaires PDF médicaux existent en trois variantes :
- **XFA pur** : structure XML embarquée dans le PDF (`/Root/AcroForm/XFA`)
- **AcroForm pur** : champs widget classiques (`/Root/AcroForm/Fields`)
- **Hybride** : contient à la fois XFA et des champs AcroForm

L'application supporte maintenant les trois.

---

## Détection automatique

Au démarrage du STEP 4, le pipeline détecte automatiquement le type :

```python
form_type = detect_form_type(empty_form_path)
# → "xfa" | "acroform" | "hybrid" | "none"
```

| Type | Action |
|---|---|
| `xfa` | Pipeline XFA uniquement (extract → fill XML → inject) |
| `acroform` | Pipeline AcroForm uniquement (pikepdf /Fields) |
| `hybrid` | XFA d'abord, puis AcroForm par-dessus |
| `none` | Erreur : formulaire non interactif |

---

## Nouveau champ dans les templates JSON : `acroform_name`

Pour les formulaires hybrides ou AcroForm purs, chaque champ peut avoir un `acroform_name`
en plus du `xml_path` :

```json
{
  "id": "2.1",
  "name": "firstName",
  "question": "Quel est le prénom du patient ?",
  "xml_path": "Seite2/patientS1Address/firstName",
  "acroform_name": "Patient.FirstName"
}
```

- `xml_path` : utilisé pour XFA (obligatoire pour les formulaires XFA/hybrides)
- `acroform_name` : utilisé pour AcroForm (obligatoire pour les formulaires AcroForm purs ou hybrides avec champs AcroForm)
- Les deux peuvent coexister sur un même champ (cas hybride)
- Si un formulaire est AcroForm pur et qu'un champ n'a pas de `acroform_name`, il est ignoré silencieusement

---

## Nommage des champs AcroForm

Pour trouver les noms exacts des champs d'un formulaire AcroForm :

```python
from core.acroform import extract_acroform_field_names
fields = extract_acroform_field_names("mon_formulaire.pdf")
print(fields)
# {"Patient.FirstName": "", "Patient.LastName": "", ...}
```

Ou via SSH sur le serveur :
```bash
docker exec df-services-orchestrator python3 -c "
from core.acroform import extract_acroform_field_names
import json
fields = extract_acroform_field_names('/app/forms/Form_LAA_ABRG.pdf')
print(json.dumps(list(fields.keys()), indent=2))
"
```

---

## Comportement pour les checkboxes AcroForm

Les cases à cocher sont détectées automatiquement (champ `/FT = /Btn` sans flags Radio/Pushbutton).

Valeurs converties automatiquement :
- Truthy → `/Yes` : "on", "true", "1", "yes", "oui", "x", "checked"
- Falsy → `/Off` : tout le reste

---

## Fichiers modifiés/créés

| Fichier | Rôle |
|---|---|
| `core/acroform.py` (nouveau) | Détection, lecture et remplissage AcroForm |
| `app.py` STEP 4 | Logique hybride, utilise `detect_form_type()` |
| Templates `*.json` | Peuvent maintenant avoir `acroform_name` (optionnel) |
