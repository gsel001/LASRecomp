"""Version 1: narrow, asset-free discovery and private-copy dependency (stdlib only).
Derived from the previously validated collector's ini_values/data_paths/copy functions.
No diagnostics, game loading, settings import or source-repository dependency.
"""
from pathlib import Path
import os
import shutil
VERSION = 1

def ini_values(path):
    values = {}
    for line in Path(path).read_text(errors='replace').splitlines():
        if '=' in line and not line.lstrip().startswith(('#',';')):
            key,value=line.split('=',1);values[key.strip()]=value.strip()
    return values

def reject_save_links(save):
    save=Path(save)
    if str(save).startswith(('/var/','/tmp/')):save=Path('/private')/save.relative_to('/')
    # Inspect lexical ancestors before resolve, including a linked save root.
    if any(p.is_symlink() for p in [save,*save.parents]):
        raise ValueError('Save path contains a symbolic link.')
    if not save.is_dir() or any(p.is_symlink() for p in save.rglob('*')):
        raise ValueError('Save source must be an existing directory without links.')

def data_paths(args,repo=None):
    repo=Path(repo) if repo else Path.home()/'Developer/LASRecomp'
    home=Path.home()/'Library/Application Support/com.peiikai.lasrecomp'
    if args.data_root:root=Path(args.data_root).expanduser()
    elif (repo/'extracted').is_dir():root=repo
    else:
        pointer=home/'data_root.txt'
        root=Path(pointer.read_text().splitlines()[0]) if pointer.is_file() and pointer.read_text().strip() else home
    root=root.expanduser().resolve()
    settings=Path(args.settings or root/'larecomp.ini').expanduser()
    if not settings.is_absolute():settings=root/settings
    if not root.is_dir() or not settings.is_file():raise ValueError('Data folder/settings not found; use explicit input options.')
    seed=ini_values(settings).get('rando_seed','')
    if seed and (Path(seed).name!=seed or seed in ('.','..')):raise ValueError('Unsupported seed path.')
    save=Path(args.save_dir or (root/'rando'/seed/'save' if seed else root/'save')).expanduser()
    if not save.is_absolute():save=root/save
    # macOS /tmp is a platform alias, not an input save-tree link. Normalize only that alias.
    if str(save).startswith('/var/'):save=Path('/private')/save.relative_to('/')
    if str(save).startswith('/tmp/'):save=Path('/private')/save.relative_to('/')
    reject_save_links(save)
    return root,settings.resolve(),save.resolve()

def prepare_private_run(scratch,settings,save,data_root,parent_env):
    scratch=Path(scratch);save=Path(save)
    reject_save_links(save)
    private_settings=scratch/'larecomp.ini';private_save=scratch/'save'
    shutil.copyfile(settings,private_settings)
    # copytree failure leaves the partial private copy for diagnosis, never mutates the source.
    shutil.copytree(save,private_save)
    return {},private_settings
