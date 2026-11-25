"""Tests d'intégration : FileManager avec le vrai système de fichiers (OsFileSystem)
dans un dossier temporaire fourni par pytest (tmp_path)."""
import pytest

from filemanager import FileManager, ErrorChoice
from fmgr import OsFileSystem
from test_fmgr import FakeSelection, FakeUI


@pytest.fixture
def tree(tmp_path):
    (tmp_path / 'a' / 'd').mkdir(parents=True)
    (tmp_path / 'a' / 'x.txt').write_text('x')
    (tmp_path / 'a' / 'd' / 'z.txt').write_text('z')
    (tmp_path / 'b').mkdir()
    return tmp_path


def manager(selected, choices=()):
    fs = OsFileSystem()
    ui = FakeUI(choices)
    return FileManager(FakeSelection([str(p) for p in selected]), fs, fs, ui), ui


def test_copy_file_and_folder(tree):
    fm, ui = manager([tree / 'a' / 'x.txt', tree / 'a' / 'd'])
    fm.copy_files(str(tree / 'b'))
    assert (tree / 'b' / 'x.txt').read_text() == 'x'
    assert (tree / 'b' / 'd' / 'z.txt').read_text() == 'z'
    assert ui.messages == ["2 file(s) copied"]


def test_copy_does_not_overwrite_existing_file(tree):
    (tree / 'b' / 'x.txt').write_text('old')
    fm, ui = manager([tree / 'a' / 'x.txt'], choices=[ErrorChoice.CANCEL])
    fm.copy_files(str(tree / 'b'))
    assert (tree / 'b' / 'x.txt').read_text() == 'old'
    assert ui.errors[0][2] == 'FileExistsError'


def test_move_then_cancel_restores(tree):
    fm, ui = manager([tree / 'a' / 'd', tree / 'a' / 'missing.txt'],
                     choices=[ErrorChoice.CANCEL])
    fm.move_files(str(tree / 'b'))
    assert (tree / 'a' / 'd' / 'z.txt').exists()
    assert not (tree / 'b' / 'd').exists()


def test_move_folder_into_itself_is_refused(tree):
    fm, ui = manager([tree / 'a'], choices=[ErrorChoice.IGNORE])
    fm.move_files(str(tree / 'a' / 'd'))
    assert ui.errors[0][2] == 'ValueError'
    assert (tree / 'a' / 'd' / 'z.txt').exists()


def test_delete_then_cancel_restores(tree):
    fm, ui = manager([tree / 'a' / 'x.txt', tree / 'a' / 'd', tree / 'a' / 'missing.txt'],
                     choices=[ErrorChoice.CANCEL])
    fm.delete_files()
    assert (tree / 'a' / 'x.txt').read_text() == 'x'
    assert (tree / 'a' / 'd' / 'z.txt').exists()


def test_delete(tree):
    fm, ui = manager([tree / 'a' / 'x.txt', tree / 'a' / 'd'])
    fm.delete_files()
    assert sorted(p.name for p in (tree / 'a').iterdir()) == []
    assert ui.messages == ["2 file(s)/folder(s) deleted"]
