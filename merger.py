#!/usr/bin/env python3
import os
import subprocess
import argparse
import atexit
from typing import List, Mapping, Optional, Set
from models import *
from models.repository import SubmoduleDef
from pprint import pprint
import json
import configparser
from utils import exec_cmd, listdir_list, pretty_print_list
import tempfile

# Configurable paths
GIT_FILTER_REPO = os.path.join(os.path.expanduser("~"), "git-filter-repo")
THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DIR = os.path.join(THIS_SCRIPT_DIR, "sandbox")

# Ensure sandbox is removed at exit (optional: remove this in debug)
atexit.register(lambda: os.system(f"rm -rf {SANDBOX_DIR}"))

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def get_all_branches(repo_path: str, verbose: bool = False, raw: bool = False) -> List[str]:
    cmd = "git branch -a"
    out = exec_cmd(cmd, cwd=repo_path)
    branches = set()
    if verbose:
        print(f"Branches in repo {repo_path}:\n{out.stdout}")
    if raw:
        return [line.strip() for line in out.stdout.splitlines()]
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        line = line.strip()
        if line.find("HEAD") != -1 or line.find("no branch") != -1:
            continue
        if line.startswith("remotes/origin/"):
            line = line[len("remotes/origin/"):]
        branches.add(line)
    return list(branches)

def get_all_submodules(repo_path: str) -> List[SubmoduleDef]:
    """
    Returns list of submodule paths in the given repo.
    """
    gitmodules_path = os.path.join(repo_path, ".gitmodules")
    if not os.path.isfile(gitmodules_path):
        return []
    config = configparser.ConfigParser()
    config.read(gitmodules_path)
    submodules = []
    for section in config.sections():
        if section.startswith("submodule "):
            path = config[section].get("path")
            if path:
                url = config[section].get("url")
                if url:
                    submodules.append(SubmoduleDef(path=path, url=url))
    return submodules


def import_meta_repo(monorepo_root_dir: str, metarepo_root_dir: str):
    """
    It is expected that both folders are git repositories, and that the metarepo
    is already cloned locally.
    """
    metarepo_branches = get_all_branches(metarepo_root_dir)
    print(f"Meta-repo branches: {metarepo_branches}")
    exec_cmd(f"git remote add metarepo {metarepo_root_dir}", cwd=monorepo_root_dir)
    exec_cmd(f"git fetch metarepo '+refs/heads/*:refs/remotes/metarepo/*'", cwd=monorepo_root_dir)
    for branch in metarepo_branches:
        print(f"=== Importing meta:{branch} ===")
        # ensure monorepo exists and branch created/overwritten to exactly meta branch
        exec_cmd(f"git checkout -B {branch} metarepo/{branch}", cwd=monorepo_root_dir)
    # cleanup
    exec_cmd(f"git remote remove metarepo", cwd=monorepo_root_dir)

def update_all_repo_branches(repo_root_dir: str):
    """
    Will fetch all branches from the origin, and update its local refs
    """
    branches = get_all_branches(repo_root_dir)
    print(f"Updating all branches in repo at {repo_root_dir}: {branches}")
    for branch in branches:
        exec_cmd(f"git checkout {branch}", cwd=repo_root_dir)
        exec_cmd(f"git pull origin {branch}", cwd=repo_root_dir)


def import_submodule(monorepo_root_dir: str, submodule_repo_url: str, submodule_path: str, expected_branches: Optional[Set[str]] = None, metarepo_tracked_branches: Optional[Set[str]] = None):
    """
    It is expected that monorepo_root_dir points to a git repository where the submodule will be imported.
    the submodule will be cloned from submodule_repo_url, and all its branches will be imported under submodule_path in the monorepo.
    """
    if not os.path.exists(GIT_FILTER_REPO):
        raise RuntimeError(f"git-filter-repo not found at {GIT_FILTER_REPO}")
    
    with tempfile.TemporaryDirectory() as tempdir:
        # First, make a minimal clone just to get branch information
        info_clone_dir = os.path.join(tempdir, "info_clone")
        print(f"Cloning repository to discover branches...")
        exec_cmd(f"git clone {submodule_repo_url} {info_clone_dir}")
        exec_cmd("git fetch --all --prune", cwd=info_clone_dir)

        # Get all branches from the bare clone
        submodule_branches = set(get_all_branches(info_clone_dir, verbose=True))
        print(f"Found branches for submodule {submodule_path}: {submodule_branches}")
        if expected_branches is not None and submodule_branches != expected_branches:
            raise RuntimeError(f"Submodule branches mismatch. Expected: {expected_branches}, Found: {submodule_branches}")
        
        # Process each branch
        branches_dir = os.path.join(tempdir, "branches")
        ensure_dir(branches_dir)

        if metarepo_tracked_branches is None:
            print(f"import_submodule(): warning: metarepo_tracked_branches is None, all submodule branches will be imported into the monorepo.")
        
        for branch in submodule_branches:
            # for each metarepo/branch, if:
            # 1. branch doesn't exist in metarepo                      -> assume we need it, create it and import submodule branch
            # 2. branch exists in metarepo and tracks submodule        -> import submodule branch into it
            # 3. branch exists in metarepo but doesn't track submodule -> skip importing submodule branch into it
            # TODO: add test cases for these 3 possible scenarios
            # TODO: for case 1, it would be better to check against the default branch of the metarepo, rather than blindly creating new branches

            # TODO: if some submodule doesn't contain a feature branch that DOES exist in the metarepo,
            # and the metarepo tracks this submodule in the feature branch, we should import the submodule's default branch into the metarepo's feature branch

            if metarepo_tracked_branches is not None and branch not in metarepo_tracked_branches:
                print(f"Skipping import of submodule {submodule_path} branch {branch} into monorepo, as metarepo branch does not track this submodule.")
                continue

            print(f"====================================")
            print(f"=== Importing {submodule_path}:{branch} ===")
            print(f"====================================")

            # Create a fresh clone of just this branch
            branch_clone_dir = os.path.join(branches_dir, f"clone_{branch.replace('/', '_')}")
            exec_cmd(f"git clone -b {branch} --single-branch {submodule_repo_url} {branch_clone_dir}")

            # Run filter-repo on the isolated clone to move everything under submodule_path
            exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {submodule_path}", cwd=branch_clone_dir)
            
            # Ensure the corresponding branch exists in monorepo (or create it)
            # Using shell OR logic: try to create, if fails then switch to existing
            exec_cmd(f"git switch -c {branch} 2>/dev/null || git switch {branch}", cwd=monorepo_root_dir)
            
            # need to remove all the files in the monorepo that are under submodule_path
            submodule_full_path_in_monorepo = os.path.join(monorepo_root_dir, submodule_path)
            if os.path.exists(submodule_full_path_in_monorepo):
                print(f"Removing existing files in monorepo at {submodule_full_path_in_monorepo} ...")
                exec_cmd(f"git rm -rf {submodule_path}", cwd=monorepo_root_dir)
                exec_cmd(f"git commit -m 'Remove existing submodule path {submodule_path} before merge'", cwd=monorepo_root_dir)
            else:
                print(f"No existing files to remove in monorepo at {submodule_full_path_in_monorepo}.")

            # Add the filtered clone as a temporary remote, and merge its branch into the monorepo branch
            branch_clone_abs = os.path.abspath(branch_clone_dir)
            remote_name = f"tmp_{branch.replace('/', '_').replace('-', '_')}"
            
            exec_cmd(f"git remote add {remote_name} {branch_clone_abs}", cwd=monorepo_root_dir)
            exec_cmd(f"git fetch {remote_name}", cwd=monorepo_root_dir)
            exec_cmd(f"git merge {remote_name}/{branch} --allow-unrelated-histories -m 'Merge submodule {submodule_path} branch {branch}'", cwd=monorepo_root_dir)
            
            # Cleanup remote (the clone directory will be cleaned up by tempdir)
            exec_cmd(f"git remote remove {remote_name}", cwd=monorepo_root_dir)


def main_flow(metarepo_url: str, monorepo_url: Optional[str] = None):
    ensure_dir(SANDBOX_DIR)
    # clone metarepo
    metarepo_root_dir = os.path.join(SANDBOX_DIR, "metarepo")
    exec_cmd(f"git clone {metarepo_url} metarepo", cwd=SANDBOX_DIR)
    update_all_repo_branches(metarepo_root_dir)

    # Prepare monorepo
    monorepo_root_dir = os.path.join(THIS_SCRIPT_DIR, "monorepo") # TODO: allow user to choose where to create it on disk
    if monorepo_url:
        exec_cmd(f"git clone {monorepo_url} monorepo", cwd=THIS_SCRIPT_DIR)
    else:
        ensure_dir(monorepo_root_dir)
        print(f"Creating a new empty repository at {monorepo_root_dir} ...")
        exec_cmd("git init --initial-branch=main", cwd=monorepo_root_dir, verbose_output=True)

    # Import metarepo
    import_meta_repo(monorepo_root_dir, metarepo_root_dir)

    # Some branches in the metarepo may or may not have some submodules
    # So we need to scan all metarepo branches for submodules, to know which submodules to import
    # for each submodule, we will track which metarepo branches track it
    imported_submodules: Mapping[SubmoduleDef, Set[str]] = dict()
    for branch in get_all_branches(metarepo_root_dir):
        print(f"--- Scanning branch {branch} for submodules ---")
        exec_cmd(f"git checkout {branch}", cwd=metarepo_root_dir)
        submodules_in_branch = get_all_submodules(metarepo_root_dir)
        for submodule in submodules_in_branch:
            if submodule not in imported_submodules:
                imported_submodules[submodule] = set()
            imported_submodules[submodule].add(branch)

    print(f"Submodules to import:")
    for submodule in imported_submodules:
        print(f"path: {submodule.path}\nurl: {submodule.url}\n")
    
    # for each submodule, we will do a fresh clone, and then process it
    for submodule in imported_submodules:
        import_submodule(monorepo_root_dir, submodule.url, submodule.path, expected_branches=None, metarepo_tracked_branches=imported_submodules[submodule])

    print("=== Merge completed ===")

# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(
        description="Merge a metarepo and its submodules into a monorepo",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "metarepo_url",
        help="URL of the metarepo to import (e.g., https://github.com/user/metarepo.git or /path/to/local/repo)"
    )
    parser.add_argument(
        "--monorepo-url",
        dest="monorepo_url",
        default=None,
        help="Optional URL of an existing monorepo to merge into. If not provided, a new empty monorepo will be created."
    )
    args = parser.parse_args()
    main_flow(args.metarepo_url, args.monorepo_url)

if __name__ == "__main__":
    main()
