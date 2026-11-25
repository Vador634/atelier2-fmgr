# Ateliers 1 et 2 - Testabilité et tests de `FileManager`

Gestionnaire de fichiers en console (`fmgr.py`) refactorisé pour rendre `FileManager` testable (atelier 1),
puis couvert par des tests unitaires, de couverture et de mutation (atelier 2).

## Équipe

- Xavier Sanchez ([@xaviersanc](https://github.com/xaviersanc))
- Emma Gailledrat ([@EmmaDotCom](https://github.com/EmmaDotCom))
- Alexandre Sanchez ([@sonical0](https://github.com/sonical0))
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

# Atelier 2 - Test

## Étape 1 - Projet de test

Dépendances de développement dans `requirements-dev.txt` (pytest, pytest-cov, cosmic-ray), configuration
de pytest dans `pytest.ini`. Les tests de l'atelier 1 passent avec pytest (16 tests).

# Atelier 1 - Étapes (une par commit)

1. **Refactorisation** : l'exploration (répertoire courant, affichage, navigation, sélection) est sortie de `FileManager` vers une nouvelle classe `FileExplorer`. `FileManager` ne garde que les traitements (copie, déplacement, suppression).
2. **Dépendances** : inversion de contrôle. `FileManager` reçoit par son constructeur des interfaces au lieu d'utiliser directement `os`, `shutil`, `FileExplorer` et la console :
   - `SelectionProvider` (implémentée par `FileExplorer`)
   - `FileSystemReader` / `FileSystemWriter` (implémentées par `OsFileSystem`)
   - `UserInterface` (implémentée par `ConsoleUserInterface`)

   Principes SOLID respectés : **L** (implémentations réelles et doublures de test interchangeables), **I** (interfaces petites, lecture et écriture séparées), **D** (`FileManager` dépend d'abstractions ; seul `main_menu()` choisit les implémentations concrètes).
   Les tests (`test_fmgr.py`) injectent un système de fichiers en mémoire et une interface utilisateur scriptée : aucun fichier réel n'est touché.
3. **Évolutions** : en cas d'erreur sur un fichier (E/S, fichier inexistant, verrouillé…), `FileManager` appelle `UserInterface.error_choice(operation, path, error)`, qui renvoie :
   - `0` : ignorer l'erreur et continuer
   - `1` : toujours ignorer les erreurs (jusqu'à la fin de l'opération en cours)
   - `2` : stopper l'opération en cours (ce qui est déjà fait est conservé)
   - `3` : annuler l'opération en cours avec **rollback** (copies supprimées, fichiers déplacés remis à leur place, fichiers supprimés restaurés : ils passent d'abord par une corbeille temporaire, vidée à la fin de l'opération)

## Diagramme de classes

```mermaid
classDiagram
    class SelectionProvider {<<interface>> +get_selected_files() +clear_selection()}
    class FileSystemReader {<<interface>> +exists() +is_file() +is_dir() +list_dir()}
    class FileSystemWriter {<<interface>> +copy() +move() +remove_file() +remove_tree() +make_temp_dir()}
    class MessageOutput {<<interface>> +show_message()}
    class UserInterface {<<interface>> +error_choice(operation, path, error) int}
    MessageOutput <|-- UserInterface
    SelectionProvider <|.. FileExplorer
    FileSystemReader <|.. OsFileSystem
    FileSystemWriter <|.. OsFileSystem
    UserInterface <|.. ConsoleUserInterface
    FileExplorer o-- FileSelector
    FileManager --> SelectionProvider
    FileManager --> FileSystemReader
    FileManager --> FileSystemWriter
    FileManager --> UserInterface
```
