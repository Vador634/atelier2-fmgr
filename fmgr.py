import os
import shutil
import tempfile

from filemanager import (SelectionProvider, FileSystemReader, FileSystemWriter,
                         UserInterface, ErrorChoice, FileManager)

""" File Manager Console Application
    Generated with Claude 3.5 Haiku
    With 2 prompts :
        Génère un programme console python qui permet d'explorer les fichiers,
        en sélectionner pour copier, déplacer et supprimer les fichiers sélectionnés.
        Une classe "métier" regroupe les fonctions de sélection, copie, déplacement
        et suppression.

        Deux rectifications : il faudrait passer le code et l'interface en anglais
        et sortir la sélection de la classe "métier"

    Refactorisé (atelier 1) :
        - étape 1 : exploration sortie de FileManager vers FileExplorer
        - étape 2 : inversion de contrôle, FileManager ne dépend plus que
          d'abstractions (interfaces) injectées par le constructeur
        - étape 3 : gestion des erreurs via UserInterface.error_choice
          (0 ignorer, 1 toujours ignorer, 2 stopper, 3 annuler + rollback)

    Atelier 2 : FileManager et ses interfaces sont dans filemanager.py
"""


# ---------------------------------------------------------------------------
# Implémentations concrètes
# ---------------------------------------------------------------------------

class OsFileSystem(FileSystemReader, FileSystemWriter):
    """Implémentation réelle basée sur os / shutil"""

    def exists(self, path):
        return os.path.exists(path)

    def is_file(self, path):
        return os.path.isfile(path)

    def is_dir(self, path):
        return os.path.isdir(path)

    def list_dir(self, path):
        return os.listdir(path)

    def copy(self, source, destination):
        if os.path.isdir(source):
            target = os.path.join(destination, os.path.basename(os.path.normpath(source)))
            return shutil.copytree(source, target)
        return shutil.copy2(source, destination)

    def move(self, source, destination):
        return shutil.move(source, destination)

    def remove_file(self, path):
        os.remove(path)

    def remove_tree(self, path):
        shutil.rmtree(path)

    def make_temp_dir(self):
        return tempfile.mkdtemp(prefix="fmgr-trash-")


class ConsoleUserInterface(UserInterface):
    """Interface utilisateur console"""

    def show_message(self, message):
        print(message)

    def error_choice(self, operation, path, error):
        print(f"\n{operation} error on '{path}': {error}")
        print(f"  {ErrorChoice.IGNORE}. Ignore and continue")
        print(f"  {ErrorChoice.ALWAYS_IGNORE}. Always ignore errors")
        print(f"  {ErrorChoice.STOP}. Stop the operation")
        print(f"  {ErrorChoice.CANCEL}. Cancel the operation (rollback)")
        while True:
            answer = input("Your choice: ").strip()
            if answer in ("0", "1", "2", "3"):
                return int(answer)
            print("Invalid choice")

    def ask(self, prompt):
        return input(prompt)


class FileSelector:
    def __init__(self, file_system=None, output=None):
        self.file_system = file_system or OsFileSystem()
        self.output = output or ConsoleUserInterface()
        self.selected_files = []
        self.current_directory_contents = []

    def load_directory_contents(self, directory_path):
        """Load the contents of a directory"""
        try:
            self.current_directory_contents = self.file_system.list_dir(directory_path)
            return self.current_directory_contents
        except Exception as e:
            self.output.show_message(f"Error loading directory contents: {e}")
            return []

    def select_files_by_indices(self, indices, directory_path):
        """Select files based on indices"""
        try:
            # Convert input string to list of indices
            selected_indices = [int(i.strip()) for i in indices.split(',')]

            # Reset previous selection
            self.selected_files.clear()

            # Select files
            for index in selected_indices:
                if 0 <= index < len(self.current_directory_contents):
                    full_path = os.path.join(directory_path, self.current_directory_contents[index])
                    self.selected_files.append(full_path)

            self.output.show_message("Selected files:")
            for file in self.selected_files:
                self.output.show_message(f" - {os.path.basename(file)}")

            return self.selected_files
        except ValueError:
            self.output.show_message("Invalid input. Please enter valid indices.")
            return []
        except Exception as e:
            self.output.show_message(f"Error selecting files: {e}")
            return []

    def get_selected_files(self):
        """Return the list of currently selected files"""
        return self.selected_files

    def clear_selection(self):
        """Clear the current file selection"""
        self.selected_files.clear()


class FileExplorer(SelectionProvider):
    """Exploration du système de fichiers : répertoire courant, affichage, navigation, sélection"""

    def __init__(self, start_path=None, file_system=None, output=None):
        self.file_system = file_system or OsFileSystem()
        self.output = output or ConsoleUserInterface()
        self.current_path = start_path or os.path.expanduser('~')
        self.file_selector = FileSelector(self.file_system, self.output)

    def display_directory_contents(self):
        """Display contents of the current directory"""
        try:
            contents = self.file_selector.load_directory_contents(self.current_path)
            self.output.show_message(f"\nCurrent Directory: {self.current_path}")
            self.output.show_message("-" * 50)
            for index, element in enumerate(contents):
                full_path = os.path.join(self.current_path, element)
                element_type = "[D] Folder" if self.file_system.is_dir(full_path) else "[F] File"
                self.output.show_message(f"{index}. {element_type}: {element}")
        except PermissionError:
            self.output.show_message("Access denied to this directory.")
        except Exception as e:
            self.output.show_message(f"Error: {e}")

    def navigate(self, index):
        """Navigate to a subdirectory"""
        try:
            contents = self.file_system.list_dir(self.current_path)
            selected_element = contents[index]
            full_path = os.path.join(self.current_path, selected_element)

            if self.file_system.is_dir(full_path):
                self.current_path = full_path
                self.display_directory_contents()
            else:
                self.output.show_message(f"Cannot open file {selected_element}")
        except Exception as e:
            self.output.show_message(f"Navigation error: {e}")

    def go_to_parent_directory(self):
        """Move to the parent directory"""
        self.current_path = os.path.dirname(self.current_path)
        self.display_directory_contents()

    def select_files(self, indices):
        """Select files of the current directory by indices"""
        return self.file_selector.select_files_by_indices(indices, self.current_path)

    # SelectionProvider
    def get_selected_files(self):
        return self.file_selector.get_selected_files()

    def clear_selection(self):
        self.file_selector.clear_selection()


def main_menu():
    # Composition des dépendances (seul endroit où l'on choisit les implémentations)
    file_system = OsFileSystem()
    ui = ConsoleUserInterface()
    file_explorer = FileExplorer(file_system=file_system, output=ui)
    file_manager = FileManager(file_explorer, file_system, file_system, ui)

    while True:
        print("\n--- File Explorer ---")
        print("1. Display Directory")
        print("2. Navigate")
        print("3. Go to Parent Directory")
        print("4. Select Files")
        print("5. Copy")
        print("6. Move")
        print("7. Delete")
        print("8. Quit")

        choice = ui.ask("Your choice: ")

        try:
            if choice == '1':
                file_explorer.display_directory_contents()

            elif choice == '2':
                index = int(ui.ask("Enter navigation index: "))
                file_explorer.navigate(index)

            elif choice == '3':
                file_explorer.go_to_parent_directory()

            elif choice == '4':
                file_explorer.display_directory_contents()
                indices = ui.ask("Enter file indices to select (comma-separated): ")
                file_explorer.select_files(indices)

            elif choice == '5':
                dest = ui.ask("Enter destination path for copying: ")
                file_manager.copy_files(dest)

            elif choice == '6':
                dest = ui.ask("Enter destination path for moving: ")
                file_manager.move_files(dest)

            elif choice == '7':
                file_manager.delete_files()

            elif choice == '8':
                print("Goodbye!")
                break

            else:
                print("Invalid choice")

        except Exception as e:
            print(f"An error occurred: {e}")


if __name__ == "__main__":
    main_menu()
