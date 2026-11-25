"""Tests unitaires de FileManager (lancer avec : python -m pytest -v)

FileManager ne dépend que d'interfaces : on lui injecte des doublures
en mémoire pour ses dépendances (sélection, système de fichiers, interface
utilisateur), aucun fichier réel n'est touché.

Organisation :
    - doublures (FakeSelection, FakeFileSystem, FakeUI)
    - copy_files, move_files, delete_files : cas usuels, extrêmes et d'erreur
    - choix de l'utilisateur en cas d'erreur (ignorer, toujours ignorer,
      stopper, annuler + rollback)
"""
import unittest

from filemanager import (FileManager, SelectionProvider, FileSystemReader,
                         FileSystemWriter, MessageOutput, UserInterface, ErrorChoice)


# ---------------------------------------------------------------------------
# Doublures
# ---------------------------------------------------------------------------

def norm(path):
    """Les chemins sont stockés avec des '/' (os.path.join met des '\\' sous Windows)
    et sans séparateur final"""
    path = path.replace('\\', '/')
    return path.rstrip('/') or path


class FakeSelection(SelectionProvider):
    def __init__(self, files):
        self.files = list(files)
        self.cleared = 0

    def get_selected_files(self):
        return self.files

    def clear_selection(self):
        self.cleared += 1
        self.files = []


class FakeFileSystem(FileSystemReader, FileSystemWriter):
    """Système de fichiers en mémoire : chemin -> 'file' | 'dir'

    Se comporte comme shutil : copy/move écrasent une cible existante, et si la
    destination n'est pas un dossier, la source est copiée/déplacée SOUS CE NOM.
    """

    def __init__(self, entries, failing=()):
        self.entries = dict(entries)
        self.failing = set(failing)  # chemins qui provoquent une erreur E/S
        self.calls = []
        self.trash_count = 0

    def _fail_if_needed(self, path):
        if path in self.failing:
            raise PermissionError(f"Locked: {path}")

    def _tree(self, path):
        return [p for p in self.entries if p == path or p.startswith(path + '/')]

    def _target(self, source, destination):
        destination = destination.rstrip('/')
        if self.entries.get(destination) != 'dir':
            return destination
        return destination + '/' + source.rsplit('/', 1)[-1]

    # -- lecture ------------------------------------------------------------
    def exists(self, path):
        return norm(path) in self.entries

    def is_file(self, path):
        return self.entries.get(norm(path)) == 'file'

    def is_dir(self, path):
        return self.entries.get(norm(path)) == 'dir'

    def list_dir(self, path):
        prefix = norm(path).rstrip('/') + '/'
        return [p[len(prefix):] for p in self.entries
                if p.startswith(prefix) and '/' not in p[len(prefix):]]

    # -- écriture -----------------------------------------------------------
    def copy(self, source, destination):
        source, destination = norm(source), norm(destination)
        self.calls.append(('copy', source, destination))
        self._fail_if_needed(source)
        if source not in self.entries:
            raise FileNotFoundError(source)
        target = self._target(source, destination)
        for p in self._tree(source):
            self.entries[target + p[len(source):]] = self.entries[p]
        return target

    def move(self, source, destination):
        source, destination = norm(source), norm(destination)
        self.calls.append(('move', source, destination))
        self._fail_if_needed(source)
        if source not in self.entries:
            raise FileNotFoundError(source)
        target = self._target(source, destination)
        for p in self._tree(source):
            self.entries[target + p[len(source):]] = self.entries.pop(p)
        return target

    def remove_file(self, path):
        path = norm(path)
        self.calls.append(('remove_file', path))
        self._fail_if_needed(path)
        del self.entries[path]

    def remove_tree(self, path):
        path = norm(path)
        self.calls.append(('remove_tree', path))
        self._fail_if_needed(path)
        for p in self._tree(path):
            del self.entries[p]

    def make_temp_dir(self):
        self.trash_count += 1
        path = f'/tmp/trash{self.trash_count}'
        self.calls.append(('make_temp_dir', path))
        self._fail_if_needed('make_temp_dir')
        self.entries[path] = 'dir'
        return path


class FakeUI(UserInterface):
    """Interface utilisateur scriptée : renvoie les choix prévus, dans l'ordre"""

    def __init__(self, choices=()):
        self.choices = list(choices)
        self.messages = []
        self.errors = []

    def show_message(self, message):
        self.messages.append(message)

    def error_choice(self, operation, path, error):
        self.errors.append((operation, norm(path), type(error).__name__))
        return self.choices.pop(0)


class FileManagerTestCase(unittest.TestCase):
    def make(self, entries, selected, failing=(), choices=()):
        self.initial = dict(entries)
        self.fs = FakeFileSystem(entries, failing)
        self.selection = FakeSelection(selected)
        self.ui = FakeUI(choices)
        self.manager = FileManager(self.selection, self.fs, self.fs, self.ui)

    def assertFiles(self, *paths):
        for path in paths:
            self.assertIn(path, self.fs.entries)

    def assertNoFiles(self, *paths):
        for path in paths:
            self.assertNotIn(path, self.fs.entries)

    def assertUnchanged(self):
        self.assertEqual(self.fs.entries, self.initial)

    def assertNoTrashLeft(self):
        self.assertEqual([p for p in self.fs.entries if p.startswith('/tmp')], [])


FILES = {'/a': 'dir', '/a/x.txt': 'file', '/a/y.txt': 'file',
         '/a/d': 'dir', '/a/d/z.txt': 'file', '/b': 'dir'}


# ---------------------------------------------------------------------------
# copy_files
# ---------------------------------------------------------------------------

class TestCopy(FileManagerTestCase):
    # -- cas usuels ---------------------------------------------------------
    def test_copy_selected_files_to_destination(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt'])
        self.manager.copy_files('/b')
        self.assertFiles('/b/x.txt', '/b/y.txt')
        self.assertFiles('/a/x.txt', '/a/y.txt')  # les sources restent

    def test_copy_clears_selection_and_reports(self):
        self.make(FILES, ['/a/x.txt'])
        self.manager.copy_files('/b')
        self.assertEqual(self.selection.get_selected_files(), [])
        self.assertEqual(self.ui.messages, ["1 file(s) copied"])
        self.assertEqual(self.ui.errors, [])

    def test_copy_folder_with_its_content(self):
        self.make(FILES, ['/a/d'])
        self.manager.copy_files('/b')
        self.assertFiles('/b/d', '/b/d/z.txt', '/a/d/z.txt')
        self.assertIn("1 file(s) copied", self.ui.messages)

    # -- cas extrêmes -------------------------------------------------------
    def test_copy_with_empty_selection(self):
        self.make(FILES, [])
        self.manager.copy_files('/b')
        self.assertUnchanged()
        self.assertEqual(self.fs.calls, [])
        self.assertEqual(self.ui.messages, ["0 file(s) copied"])

    def test_copy_same_file_selected_twice_is_copied_once(self):
        self.make(FILES, ['/a/x.txt', '/a/x.txt'])
        self.manager.copy_files('/b')
        self.assertEqual(self.fs.calls, [('copy', '/a/x.txt', '/b')])
        self.assertEqual(self.ui.errors, [])
        self.assertIn("1 file(s) copied", self.ui.messages)

    def test_copy_destination_with_trailing_separator(self):
        self.make(FILES, ['/a/x.txt'])
        self.manager.copy_files('/b/')
        self.assertFiles('/b/x.txt')
        self.assertEqual(self.ui.errors, [])

    # -- cas d'erreur -------------------------------------------------------
    def test_copy_missing_file_asks_user(self):
        self.make(FILES, ['/a/missing.txt', '/a/x.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.copy_files('/b')
        self.assertEqual(self.ui.errors, [('Copy', '/a/missing.txt', 'FileNotFoundError')])
        self.assertFiles('/b/x.txt')
        self.assertNotIn(('copy', '/a/missing.txt', '/b'), self.fs.calls)

    def test_copy_to_missing_destination_does_nothing(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt'])
        self.manager.copy_files('/nowhere')
        self.assertUnchanged()  # pas de fichier '/nowhere' créé
        self.assertEqual(self.fs.calls, [])
        self.assertEqual(self.ui.messages, ["Destination is not a folder: /nowhere"])
        self.assertEqual(self.selection.get_selected_files(), ['/a/x.txt', '/a/y.txt'])

    def test_copy_to_a_file_does_nothing(self):
        self.make(FILES, ['/a/x.txt'])
        self.manager.copy_files('/a/y.txt')
        self.assertUnchanged()  # y.txt n'est pas écrasé
        self.assertEqual(self.ui.messages, ["Destination is not a folder: /a/y.txt"])

    def test_copy_to_empty_destination_does_nothing(self):
        self.make(FILES, ['/a/x.txt'])
        self.manager.copy_files('')
        self.assertUnchanged()
        self.assertEqual(self.fs.calls, [])

    def test_copy_does_not_overwrite_existing_file(self):
        self.make(dict(FILES, **{'/b/x.txt': 'file'}), ['/a/x.txt'],
                  choices=[ErrorChoice.IGNORE])
        self.manager.copy_files('/b')
        self.assertEqual(self.ui.errors, [('Copy', '/a/x.txt', 'FileExistsError')])
        self.assertEqual(self.fs.calls, [])
        self.assertIn("0 file(s) copied", self.ui.messages)

    def test_copy_into_source_folder_is_an_error(self):
        self.make(FILES, ['/a/x.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.copy_files('/a')
        self.assertEqual(self.ui.errors, [('Copy', '/a/x.txt', 'FileExistsError')])
        self.assertUnchanged()

    def test_copy_folder_into_itself_is_an_error(self):
        self.make(FILES, ['/a/d'], choices=[ErrorChoice.IGNORE])
        self.manager.copy_files('/a/d')
        self.assertEqual(self.ui.errors, [('Copy', '/a/d', 'ValueError')])
        self.assertUnchanged()

    def test_copy_folder_into_its_subfolder_is_an_error(self):
        self.make(dict(FILES, **{'/a/d/e': 'dir'}), ['/a/d'], choices=[ErrorChoice.IGNORE])
        self.manager.copy_files('/a/d/e')
        self.assertEqual(self.ui.errors, [('Copy', '/a/d', 'ValueError')])
        self.assertUnchanged()

    def test_copy_folder_into_sibling_with_same_prefix_is_allowed(self):
        self.make(dict(FILES, **{'/a/dd': 'dir'}), ['/a/d'])
        self.manager.copy_files('/a/dd')
        self.assertEqual(self.ui.errors, [])
        self.assertFiles('/a/dd/d/z.txt')

    def test_copy_folder_to_relative_destination(self):
        # chemin relatif + chemin absolu : os.path.commonpath lève ValueError
        self.make(dict(FILES, **{'b': 'dir'}), ['/a/d'])
        self.manager.copy_files('b')
        self.assertEqual(self.ui.errors, [])
        self.assertFiles('b/d/z.txt')

    def test_cancel_copy_keeps_previously_existing_file(self):
        # sans contrôle, la copie écrasait /b/y.txt puis le rollback le supprimait
        self.make(dict(FILES, **{'/b/y.txt': 'file'}), ['/a/x.txt', '/a/y.txt'],
                  choices=[ErrorChoice.CANCEL])
        self.manager.copy_files('/b')
        self.assertUnchanged()


# ---------------------------------------------------------------------------
# move_files
# ---------------------------------------------------------------------------

class TestMove(FileManagerTestCase):
    # -- cas usuels ---------------------------------------------------------
    def test_move_selected_files(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt'])
        self.manager.move_files('/b')
        self.assertFiles('/b/x.txt', '/b/y.txt')
        self.assertNoFiles('/a/x.txt', '/a/y.txt')
        self.assertEqual(self.ui.messages, ["2 file(s) moved"])
        self.assertEqual(self.selection.get_selected_files(), [])

    def test_move_folder_with_its_content(self):
        self.make(FILES, ['/a/d'])
        self.manager.move_files('/b')
        self.assertFiles('/b/d', '/b/d/z.txt')
        self.assertNoFiles('/a/d', '/a/d/z.txt')

    # -- cas extrêmes -------------------------------------------------------
    def test_move_with_empty_selection(self):
        self.make(FILES, [])
        self.manager.move_files('/b')
        self.assertUnchanged()
        self.assertEqual(self.fs.calls, [])
        self.assertEqual(self.ui.messages, ["0 file(s) moved"])

    def test_move_same_file_selected_twice_is_moved_once(self):
        self.make(FILES, ['/a/x.txt', '/a/x.txt'])
        self.manager.move_files('/b')
        self.assertEqual(self.ui.errors, [])
        self.assertFiles('/b/x.txt')
        self.assertIn("1 file(s) moved", self.ui.messages)

    # -- cas d'erreur -------------------------------------------------------
    def test_move_missing_file_asks_user(self):
        self.make(FILES, ['/a/missing.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.move_files('/b')
        self.assertEqual(self.ui.errors, [('Move', '/a/missing.txt', 'FileNotFoundError')])
        self.assertEqual(self.fs.calls, [])

    def test_move_to_missing_destination_does_nothing(self):
        # sans contrôle, x.txt était renommé en /nowhere puis y.txt l'écrasait
        self.make(FILES, ['/a/x.txt', '/a/y.txt'])
        self.manager.move_files('/nowhere')
        self.assertUnchanged()
        self.assertEqual(self.ui.messages, ["Destination is not a folder: /nowhere"])
        self.assertEqual(self.selection.get_selected_files(), ['/a/x.txt', '/a/y.txt'])

    def test_move_to_a_file_does_nothing(self):
        self.make(FILES, ['/a/x.txt'])
        self.manager.move_files('/a/y.txt')
        self.assertUnchanged()

    def test_move_does_not_overwrite_existing_file(self):
        self.make(dict(FILES, **{'/b/x.txt': 'file'}), ['/a/x.txt', '/a/y.txt'],
                  choices=[ErrorChoice.IGNORE])
        self.manager.move_files('/b')
        self.assertEqual(self.ui.errors, [('Move', '/a/x.txt', 'FileExistsError')])
        self.assertFiles('/a/x.txt', '/b/x.txt', '/b/y.txt')
        self.assertIn("1 file(s) moved", self.ui.messages)

    def test_move_into_its_own_folder_is_an_error(self):
        self.make(FILES, ['/a/x.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.move_files('/a')
        self.assertEqual(self.ui.errors, [('Move', '/a/x.txt', 'FileExistsError')])
        self.assertUnchanged()

    def test_move_folder_into_itself_is_an_error(self):
        self.make(FILES, ['/a/d'], choices=[ErrorChoice.IGNORE])
        self.manager.move_files('/a/d')
        self.assertEqual(self.ui.errors, [('Move', '/a/d', 'ValueError')])
        self.assertUnchanged()

    def test_move_folder_into_its_parent_folder_tree_is_an_error(self):
        self.make(FILES, ['/a'], choices=[ErrorChoice.IGNORE])
        self.manager.move_files('/a/d')
        self.assertEqual(self.ui.errors, [('Move', '/a', 'ValueError')])
        self.assertUnchanged()

    def test_cancel_move_restores_moved_folder(self):
        self.make(FILES, ['/a/d', '/a/x.txt'], failing={'/a/x.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.move_files('/b')
        self.assertUnchanged()


# ---------------------------------------------------------------------------
# delete_files
# ---------------------------------------------------------------------------

class TestDelete(FileManagerTestCase):
    # -- cas usuels ---------------------------------------------------------
    def test_delete_file_and_directory(self):
        self.make(FILES, ['/a/x.txt', '/a/d'])
        self.manager.delete_files()
        self.assertNoFiles('/a/x.txt', '/a/d', '/a/d/z.txt')
        self.assertFiles('/a/y.txt', '/b')
        self.assertEqual(self.ui.messages, ["2 file(s)/folder(s) deleted"])
        self.assertEqual(self.selection.get_selected_files(), [])

    def test_no_temp_trash_left_after_delete(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt'])
        self.manager.delete_files()
        self.assertNoTrashLeft()

    # -- cas extrêmes -------------------------------------------------------
    def test_delete_with_empty_selection(self):
        self.make(FILES, [])
        self.manager.delete_files()
        self.assertEqual(self.fs.calls, [])
        self.assertUnchanged()
        self.assertEqual(self.ui.messages, ["0 file(s)/folder(s) deleted"])

    def test_delete_same_file_selected_twice_is_deleted_once(self):
        self.make(FILES, ['/a/x.txt', '/a/x.txt'])
        self.manager.delete_files()
        self.assertEqual(self.ui.errors, [])
        self.assertEqual(self.ui.messages, ["1 file(s)/folder(s) deleted"])

    def test_delete_files_with_same_name_from_different_folders(self):
        # elles passent par la corbeille : la 2e ne doit pas écraser la 1re
        self.make(dict(FILES, **{'/b/x.txt': 'file'}), ['/a/x.txt', '/b/x.txt', '/a/y.txt'],
                  failing={'/a/y.txt'}, choices=[ErrorChoice.CANCEL])
        self.manager.delete_files()
        self.assertUnchanged()
        self.assertNoTrashLeft()

    def test_delete_folder_and_its_content_both_selected(self):
        self.make(FILES, ['/a/d', '/a/d/z.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.delete_files()
        self.assertNoFiles('/a/d', '/a/d/z.txt')
        self.assertEqual(self.ui.errors, [('Delete', '/a/d/z.txt', 'FileNotFoundError')])
        self.assertNoTrashLeft()

    # -- cas d'erreur -------------------------------------------------------
    def test_delete_missing_file_asks_user(self):
        self.make(FILES, ['/a/missing.txt', '/a/x.txt'], choices=[ErrorChoice.IGNORE])
        self.manager.delete_files()
        self.assertEqual(self.ui.errors, [('Delete', '/a/missing.txt', 'FileNotFoundError')])
        self.assertNoFiles('/a/x.txt')
        self.assertIn("1 file(s)/folder(s) deleted", self.ui.messages)

    def test_delete_locked_file_asks_user(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt'], failing={'/a/x.txt'},
                  choices=[ErrorChoice.IGNORE])
        self.manager.delete_files()
        self.assertEqual(self.ui.errors, [('Delete', '/a/x.txt', 'PermissionError')])
        self.assertFiles('/a/x.txt')
        self.assertNoFiles('/a/y.txt')
        self.assertNoTrashLeft()

    def test_delete_when_trash_cannot_be_created(self):
        self.make(FILES, ['/a/x.txt'], failing={'make_temp_dir'},
                  choices=[ErrorChoice.IGNORE])
        self.manager.delete_files()
        self.assertEqual(self.ui.errors, [('Delete', '/a/x.txt', 'PermissionError')])
        self.assertFiles('/a/x.txt')
        self.assertIn("0 file(s)/folder(s) deleted", self.ui.messages)

    def test_trash_removal_error_is_reported(self):
        self.make(FILES, ['/a/x.txt'], failing={'/tmp/trash1'})
        self.manager.delete_files()  # ne doit pas lever d'exception
        self.assertIn("1 file(s)/folder(s) deleted", self.ui.messages)
        self.assertTrue(any(m.startswith("Trash cleanup error") for m in self.ui.messages))

    def test_stop_delete_keeps_deleted_files(self):
        self.make(FILES, ['/a/x.txt', '/a/y.txt', '/a/d'], failing={'/a/y.txt'},
                  choices=[ErrorChoice.STOP])
        self.manager.delete_files()
        self.assertNoFiles('/a/x.txt')
        self.assertFiles('/a/y.txt', '/a/d')
        self.assertNoTrashLeft()
        self.assertEqual(self.ui.messages, ["Delete stopped", "1 file(s)/folder(s) deleted"])


# ---------------------------------------------------------------------------
# Choix de l'utilisateur en cas d'erreur (UserInterface.error_choice)
# ---------------------------------------------------------------------------

class TestErrorChoice(FileManagerTestCase):
    FILES = {'/a': 'dir', '/a/1.txt': 'file', '/a/2.txt': 'file', '/a/3.txt': 'file',
             '/a/4.txt': 'file', '/b': 'dir'}
    SELECTED = ['/a/1.txt', '/a/2.txt', '/a/3.txt', '/a/4.txt']

    def test_no_error_does_not_ask_user(self):
        self.make(self.FILES, self.SELECTED)
        self.manager.copy_files('/b')
        self.assertEqual(self.ui.errors, [])
        self.assertIn("4 file(s) copied", self.ui.messages)

    def test_ignore_continues_and_asks_again_next_error(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/2.txt', '/a/3.txt'},
                  choices=[ErrorChoice.IGNORE, ErrorChoice.IGNORE])
        self.manager.copy_files('/b')
        self.assertEqual(self.ui.errors, [('Copy', '/a/2.txt', 'PermissionError'),
                                          ('Copy', '/a/3.txt', 'PermissionError')])
        self.assertFiles('/b/1.txt', '/b/4.txt')
        self.assertEqual(self.ui.messages, ["2 file(s) copied"])
        self.assertEqual(self.selection.cleared, 1)

    def test_always_ignore_does_not_ask_again(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/2.txt', '/a/3.txt'},
                  choices=[ErrorChoice.ALWAYS_IGNORE])
        self.manager.copy_files('/b')
        self.assertEqual(len(self.ui.errors), 1)
        self.assertFiles('/b/1.txt', '/b/4.txt')
        self.assertEqual(self.ui.messages, ["2 file(s) copied"])

    def test_always_ignore_only_lasts_for_current_operation(self):
        self.make(self.FILES, ['/a/2.txt'], failing={'/a/2.txt'},
                  choices=[ErrorChoice.ALWAYS_IGNORE, ErrorChoice.IGNORE])
        self.manager.copy_files('/b')
        self.selection.files = ['/a/2.txt']
        self.manager.copy_files('/b')
        self.assertEqual(len(self.ui.errors), 2)

    def test_stop_keeps_done_operations(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/3.txt'},
                  choices=[ErrorChoice.STOP])
        self.manager.move_files('/b')
        self.assertFiles('/b/1.txt', '/b/2.txt', '/a/3.txt')
        self.assertFiles('/a/4.txt')  # jamais traité
        self.assertNotIn(('move', '/a/4.txt', '/b'), self.fs.calls)
        self.assertEqual(self.ui.messages, ["Move stopped", "2 file(s) moved"])
        self.assertEqual(self.selection.get_selected_files(), [])

    def test_unknown_choice_stops_the_operation(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/1.txt'}, choices=[42])
        self.manager.copy_files('/b')
        self.assertEqual(self.ui.messages, ["Copy stopped", "0 file(s) copied"])
        self.assertEqual(len(self.fs.calls), 1)

    def test_cancel_rolls_back_copy(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/3.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.copy_files('/b')
        self.assertUnchanged()
        self.assertEqual(self.selection.get_selected_files(), self.SELECTED)
        self.assertEqual(self.ui.messages, ["Copy cancelled, 2 operation(s) rolled back"])

    def test_cancel_rolls_back_in_reverse_order(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/3.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.move_files('/b')
        rollback = [c for c in self.fs.calls if c[1].startswith('/b/')]
        self.assertEqual(rollback, [('move', '/b/2.txt', '/a'), ('move', '/b/1.txt', '/a')])

    def test_cancel_rolls_back_move(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/3.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.move_files('/b')
        self.assertUnchanged()
        self.assertEqual(self.ui.messages, ["Move cancelled, 2 operation(s) rolled back"])

    def test_cancel_rolls_back_delete(self):
        files = dict(self.FILES, **{'/a/d': 'dir', '/a/d/z.txt': 'file'})
        self.make(files, ['/a/d', '/a/1.txt', '/a/3.txt'], failing={'/a/3.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.delete_files()
        self.assertUnchanged()  # tout restauré
        self.assertNoTrashLeft()
        self.assertEqual(self.ui.messages, ["Delete cancelled, 2 operation(s) rolled back"])

    def test_cancel_at_first_file_rolls_back_nothing(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/1.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.copy_files('/b')
        self.assertUnchanged()
        self.assertEqual(self.ui.messages, ["Copy cancelled, 0 operation(s) rolled back"])

    def test_rollback_error_is_reported_and_rollback_continues(self):
        self.make(self.FILES, self.SELECTED, failing={'/a/3.txt', '/b/2.txt'},
                  choices=[ErrorChoice.CANCEL])
        self.manager.copy_files('/b')
        self.assertIn("Rollback error: Locked: /b/2.txt", self.ui.messages)
        self.assertNoFiles('/b/1.txt')  # le rollback a continué après l'erreur


# ---------------------------------------------------------------------------
# Contrat des interfaces (mutation testing : mutants @abstractmethod retiré)
# ---------------------------------------------------------------------------

class TestInterfaces(unittest.TestCase):
    EXPECTED = {
        SelectionProvider: {'get_selected_files', 'clear_selection'},
        FileSystemReader: {'exists', 'is_file', 'is_dir', 'list_dir'},
        FileSystemWriter: {'copy', 'move', 'remove_file', 'remove_tree', 'make_temp_dir'},
        MessageOutput: {'show_message'},
        UserInterface: {'show_message', 'error_choice'},
    }

    def test_interfaces_declare_their_abstract_methods(self):
        for interface, methods in self.EXPECTED.items():
            with self.subTest(interface=interface.__name__):
                self.assertEqual(interface.__abstractmethods__, frozenset(methods))
                with self.assertRaises(TypeError):
                    interface()


if __name__ == '__main__':
    unittest.main()
