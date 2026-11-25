# Atelier 2 - Test de `FileManager`

Tests unitaires de la classe `FileManager` d'un gestionnaire de fichiers en console (`fmgr.py`), en simulant
ses dépendances (sélection, système de fichiers, interface utilisateur), puis couverture de code et tests de mutation.

| Fichier | Rôle |
|---|---|
| `filemanager.py` | `FileManager` et les interfaces dont il dépend (classe testée) |
| `fmgr.py` | implémentations concrètes, exploration, menu console |
| `test_fmgr.py` | tests unitaires de `FileManager` avec doublures en mémoire |
| `test_os_filesystem.py` | tests d'intégration sur un vrai dossier temporaire |
| `cosmic-ray.toml` | configuration des tests de mutation |

## Équipe

- Emma Gailledrat ([@EmmaDotCom](https://github.com/EmmaDotCom))
- Kilian Carasco ([@Vador634](https://github.com/Vador634))

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows (Linux/macOS : source .venv/bin/activate)
pip install -r requirements-dev.txt
```

## Lancer

```bash
python fmgr.py              # application console
python -m pytest -v         # tests unitaires (ou : python -m unittest -v)
```

## Étape 1 - Projet de test

Dépendances de développement dans `requirements-dev.txt` (pytest, pytest-cov, cosmic-ray), configuration
de pytest dans `pytest.ini`. Les 16 tests de départ passent avec pytest.

## Étape 2 - Tests

- `test_fmgr.py` : tests unitaires de `copy_files`, `move_files` et `delete_files` (cas usuels, extrêmes,
  d'erreur) et des choix de l'utilisateur en cas d'erreur. Les dépendances de `FileManager` sont simulées
  par des doublures en mémoire (`FakeSelection`, `FakeFileSystem`, `FakeUI`) ; `FakeFileSystem` reproduit
  le comportement de `shutil` (écrasement de la cible, destination inexistante prise comme nouveau nom).
- `test_os_filesystem.py` : quelques tests d'intégration avec le vrai système de fichiers (dossier
  temporaire `tmp_path`).

Défauts révélés par les tests puis corrigés dans `FileManager` :

| Cas | Avant | Après |
|---|---|---|
| Destination inexistante ou fichier | source copiée/déplacée sous ce nom, les fichiers s'écrasent | opération refusée, sélection conservée |
| Fichier de même nom déjà dans la destination | écrasé sans prévenir, puis **supprimé** par un rollback | erreur `FileExistsError` proposée à l'utilisateur |
| Dossier copié/déplacé dans lui-même ou un sous-dossier | erreur de `shutil` ou copie récursive | erreur `ValueError` proposée à l'utilisateur |
| Fichier sélectionné deux fois | traité deux fois | traité une seule fois |
| Suppression de fichiers de même nom | collision dans la corbeille (rollback faux) | une corbeille par élément |
| Erreur au vidage de la corbeille | exception non gérée | message `Trash cleanup error` |
| Copie d'un dossier (`OsFileSystem`) | impossible (`copy2`) | `copytree` |

## Étape 3 - Couverture et tests de mutation

`FileManager` et ses interfaces sont isolés dans `filemanager.py` pour cibler la couverture et la mutation
sur la classe testée (le menu console et l'exploration restent dans `fmgr.py`).

### Couverture (lignes + branchements `if/else`)

```bash
python -m pytest --cov=filemanager --cov-branch --cov-report=term-missing --cov-report=html
```

Rapport détaillé dans `htmlcov/index.html`.

| Rapport | Lignes non couvertes | Traitement |
|---|---|---|
| 1er passage : 99 % | `except ValueError` de `_is_same_or_inside` | situation réelle non testée (destination relative, ou autre lecteur sous Windows) : test ajouté |
| 2e passage : **100 %** lignes et branches | - | - |

### Tests de mutation (Cosmic Ray)

`mutmut` ne fonctionne pas nativement sous Windows (WSL requis) : on utilise [Cosmic Ray](https://cosmic-ray.readthedocs.io/),
configuré dans `cosmic-ray.toml` (mutation de `filemanager.py`, tests `test_fmgr.py` + `test_os_filesystem.py`).

```bash
# Windows : forcer l'UTF-8, sinon la sortie de pytest est mal décodée (mutants classés « incompetent »)
set PYTHONUTF8=1                                   # PowerShell : $env:PYTHONUTF8=1
cosmic-ray init cosmic-ray.toml session.sqlite     # liste les mutants
cosmic-ray exec cosmic-ray.toml session.sqlite     # exécute les tests sur chaque mutant
cr-report --surviving-only session.sqlite          # mutants survivants (ou : python -m cosmic_ray.tools.report)
cr-html session.sqlite > mutation.html             # rapport HTML
```

| Passage | Mutants | Tués | Survivants |
|---|---|---|---|
| 1er | 85 | 64 | 21 (une issue par mutant : #1 à #21) |
| après corrections | 85 | 81 | 4 (équivalents, non pertinents) |

| Issues | Mutant survivant | Pertinent | Traitement |
|---|---|---|---|
| #1 à #13 | `@abstractmethod` retiré d'une méthode d'interface | oui | test du contrat abstrait des interfaces |
| #14, #15 | `IGNORE = -1`, `CANCEL = 4` | oui | test des valeurs 0-3 de `ErrorChoice` (contrat avec la console) |
| #16, #17 | `choice == IGNORE / ALWAYS_IGNORE` remplacé par `<=` | oui | test d'un choix négatif (doit stopper) |
| #18 à #20 | `==` remplacé par `is` sur les choix | non | équivalent : CPython met en cache les petits entiers |
| #21 | `commonpath(...) == folder` remplacé par `>=` | non | équivalent : `commonpath` est un préfixe de `folder`, `>=` n'est vrai qu'en cas d'égalité |
