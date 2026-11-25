"""Traitements sur les fichiers (FileManager) et abstractions dont il dépend.

Module séparé de fmgr.py (implémentations concrètes, exploration, menu console)
pour cibler précisément les tests de couverture et de mutation.
"""
import os
from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Interfaces (abstractions)
#   - ISP : interfaces petites et spécialisées, chaque client ne dépend que
#     de ce qu'il utilise
#   - DIP : FileManager dépend de ces abstractions, pas de os/shutil, ni de
#     FileExplorer, ni de la console
#   - LSP : toute implémentation (réelle ou factice de test) est substituable
# ---------------------------------------------------------------------------

class SelectionProvider(ABC):
    """Fournit la liste des fichiers sélectionnés"""

    @abstractmethod
    def get_selected_files(self):
        """Return the list of selected file paths"""

    @abstractmethod
    def clear_selection(self):
        """Clear the current selection"""


class FileSystemReader(ABC):
    """Consultation du système de fichiers"""

    @abstractmethod
    def exists(self, path): ...

    @abstractmethod
    def is_file(self, path): ...

    @abstractmethod
    def is_dir(self, path): ...

    @abstractmethod
    def list_dir(self, path): ...


class FileSystemWriter(ABC):
    """Modification du système de fichiers"""

    @abstractmethod
    def copy(self, source, destination):
        """Copy source into destination, return the created path"""

    @abstractmethod
    def move(self, source, destination):
        """Move source into destination, return the new path"""

    @abstractmethod
    def remove_file(self, path): ...

    @abstractmethod
    def remove_tree(self, path): ...

    @abstractmethod
    def make_temp_dir(self):
        """Create a temporary directory (used as trash for rollback)"""


class MessageOutput(ABC):
    """Affichage de messages à l'utilisateur"""

    @abstractmethod
    def show_message(self, message): ...


class ErrorChoice:
    """Choix possibles de l'utilisateur après une erreur"""
    IGNORE = 0          # ignorer l'erreur et continuer
    ALWAYS_IGNORE = 1   # toujours ignorer les erreurs (pour l'opération en cours)
    STOP = 2            # stopper l'opération en cours
    CANCEL = 3          # annuler l'opération en cours + rollback


class UserInterface(MessageOutput):
    """Interface utilisateur dont dépend FileManager"""

    @abstractmethod
    def error_choice(self, operation, path, error):
        """Informe l'utilisateur de l'erreur et renvoie son choix (voir ErrorChoice)"""


class FileManager:
    """Traitements sur les fichiers sélectionnés : copie, déplacement, suppression.

    Toutes les dépendances sont injectées par le constructeur (inversion de contrôle).
    """

    def __init__(self, selection: SelectionProvider, reader: FileSystemReader,
                 writer: FileSystemWriter, ui: UserInterface):
        self.selection = selection
        self.reader = reader
        self.writer = writer
        self.ui = ui

    # -- moteur commun ------------------------------------------------------
    def _run(self, operation, action):
        """Applique action(file) à chaque fichier sélectionné (une seule fois chacun).

        action renvoie une fonction d'annulation, utilisée pour le rollback.
        Renvoie le nombre de fichiers traités, ou None si l'opération est annulée.
        """
        undo_stack = []
        always_ignore = False
        for file in dict.fromkeys(self.selection.get_selected_files()):
            try:
                undo_stack.append(action(file))
            except Exception as e:
                if always_ignore:
                    continue
                choice = self.ui.error_choice(operation, file, e)
                if choice == ErrorChoice.IGNORE:
                    continue
                if choice == ErrorChoice.ALWAYS_IGNORE:
                    always_ignore = True
                    continue
                if choice == ErrorChoice.CANCEL:
                    self._rollback(undo_stack)
                    self.ui.show_message(
                        f"{operation} cancelled, {len(undo_stack)} operation(s) rolled back")
                    return None
                # STOP (ou choix inconnu) : on s'arrête, ce qui est fait reste fait
                self.ui.show_message(f"{operation} stopped")
                break
        self.selection.clear_selection()
        return len(undo_stack)

    def _rollback(self, undo_stack):
        for undo in reversed(undo_stack):
            try:
                undo()
            except Exception as e:
                self.ui.show_message(f"Rollback error: {e}")

    def _check_destination(self, destination):
        """Une destination qui n'est pas un dossier existant est refusée
        (sinon shutil copie/déplace la source sous ce nom)"""
        if self.reader.is_dir(destination):
            return True
        self.ui.show_message(f"Destination is not a folder: {destination}")
        return False

    def _check_source(self, file, destination):
        """Vérifie qu'un élément peut être copié/déplacé dans destination,
        renvoie le chemin cible"""
        self._check_exists(file)
        if _is_same_or_inside(destination, file):
            raise ValueError(f"Cannot put a folder into itself: {file}")
        target = os.path.join(destination, os.path.basename(file))
        if self.reader.exists(target):
            raise FileExistsError(f"Already exists: {target}")
        return target

    def _check_exists(self, file):
        if not self.reader.exists(file):
            raise FileNotFoundError(f"File not found: {file}")

    def _remove(self, path):
        if self.reader.is_dir(path):
            self.writer.remove_tree(path)
        else:
            self.writer.remove_file(path)

    # -- opérations ---------------------------------------------------------
    def copy_files(self, destination):
        """Copy selected files"""
        if not self._check_destination(destination):
            return

        def action(file):
            self._check_source(file, destination)
            target = self.writer.copy(file, destination)
            return lambda: self._remove(target)

        done = self._run("Copy", action)
        if done is not None:
            self.ui.show_message(f"{done} file(s) copied")

    def move_files(self, destination):
        """Move selected files"""
        if not self._check_destination(destination):
            return

        def action(file):
            self._check_source(file, destination)
            origin = os.path.dirname(file)
            target = self.writer.move(file, destination)
            return lambda: self.writer.move(target, origin)

        done = self._run("Move", action)
        if done is not None:
            self.ui.show_message(f"{done} file(s) moved")

    def delete_files(self):
        """Delete selected files.

        Chaque élément est d'abord déplacé dans sa propre corbeille temporaire
        (pas de collision entre fichiers de même nom), ce qui permet le
        rollback ; les corbeilles sont vidées à la fin de l'opération.
        """
        trashes = []

        def action(file):
            self._check_exists(file)
            trash = self.writer.make_temp_dir()
            trashes.append(trash)
            origin = os.path.dirname(file)
            trashed = self.writer.move(file, trash)
            return lambda: self.writer.move(trashed, origin)

        done = self._run("Delete", action)
        for trash in trashes:
            try:
                self._remove(trash)
            except Exception as e:
                self.ui.show_message(f"Trash cleanup error: {e}")
        if done is not None:
            self.ui.show_message(f"{done} file(s)/folder(s) deleted")


def _is_same_or_inside(path, folder):
    """True si path est folder lui-même ou se trouve dans folder"""
    path, folder = os.path.normpath(path), os.path.normpath(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # lecteurs différents (Windows) ou chemins mélangés
        return False
