#!/usr/bin/env python3
import os
import subprocess
import argparse
import atexit
from typing import Annotated, List, Mapping, Optional, Set
from models import *
from models.repository import SubmoduleDef
from pprint import pprint
import json
import configparser
from utils import exec_cmd, header_string, listdir_list, pretty_print_list
import tempfile
from dataclasses import dataclass

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

def get_head_branch(repo_path: str) -> Optional[str]:
    """
    Returns the default branch of the given repo, or None if it cannot be determined.
    """
    cmd = "git rev-parse --abbrev-ref HEAD"
    out = exec_cmd(cmd, cwd=repo_path)
    default_branch = out.stdout.strip()
    if default_branch == "HEAD" or default_branch == "no branch" or default_branch == "":
        return None
    return default_branch


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
    returns the list of all repo branches.
    """
    branches = get_all_branches(repo_root_dir)
    print(f"Updating all branches in repo at {repo_root_dir}: {branches}")
    for branch in branches:
        exec_cmd(f"git checkout {branch}", cwd=repo_root_dir)
        exec_cmd(f"git pull origin {branch}", cwd=repo_root_dir)
    return branches


def import_submodule(monorepo_root_dir: str,
                     submodule_repo_url: str,
                     submodule_path: str,
                     metarepo_default_branch: str,
                     metarepo_branches: Set[str],
                     expected_branches: Optional[Set[str]] = None,
                     metarepo_tracked_branches: Optional[Set[str]] = None):
    """
    It is expected that monorepo_root_dir points to a git repository where the submodule will be imported.
    the submodule will be cloned from submodule_repo_url, and all its branches will be imported under submodule_path in the monorepo.

    metarepo_tracked_branches: all branches in the metarepo that track this submodule.
    """
    if not os.path.exists(GIT_FILTER_REPO):
        raise RuntimeError(f"git-filter-repo not found at {GIT_FILTER_REPO}")
    
    with tempfile.TemporaryDirectory() as tempdir:
        # First, make a minimal clone just to get branch information
        info_clone_dir = os.path.join(tempdir, "info_clone")
        print(f"Cloning repository to discover branches...")
        exec_cmd(f"git clone {submodule_repo_url} {info_clone_dir}")
        exec_cmd("git fetch --all --prune", cwd=info_clone_dir)

        # Get the default branch (after cloning, HEAD points to the default branch)
        submodule_default_branch = get_head_branch(info_clone_dir)

        # Get all branches from the fresh clone
        submodule_branches = set(get_all_branches(info_clone_dir))
        print(f"Found branches for submodule {submodule_path}: {submodule_branches}")
        if expected_branches is not None and submodule_branches != expected_branches:
            raise RuntimeError(f"Submodule branches mismatch. Expected: {expected_branches}, Found: {submodule_branches}")
        
        # Process each branch
        branches_dir = os.path.join(tempdir, "branches")
        ensure_dir(branches_dir)

        if metarepo_tracked_branches is None:
            print(f"import_submodule(): warning: metarepo_tracked_branches is None, all submodule branches will be imported into the monorepo.")
        
        # branches_clusure: all branches that need to be considered for this submodule
        # if the submodule itself doesn't contain some branch from the closure, we will use the submodule's default branch instead
        branches_closure = submodule_branches.copy()
        if metarepo_tracked_branches is not None:
            branches_closure.update(metarepo_tracked_branches)

        for branch in branches_closure:
            # for each {metarepo/branch}, if:
            # 1. branch exists in metarepo but doesn't track submodule -> skip importing submodule branch into it
            # 2. branch exists in metarepo, exists in submodule        -> import submodule branch into it (if submodule is tracked in the metarepo branch)
            # 3. branch exists in metarepo, doesn't exist in submodule -> import the submodule's default branch (if needed, see above)
            # 4. branch doesn't exist in metarepo, exists in submodule -> branch out from metarepo's default branch, import the submodule (if needed, see above)
            # TODO: add test cases for all possible scenarios
            
            # NOTE: in case 4, it is assumed that the metarepo itself was already imported into the monorepo,
            # so the default branch should exist fully in the monorepo, and it is safe to branch out from it.

            # case 1: branch exists in metarepo but doesn't track submodule, or doesn't exist and default branch doesn't track it either
            #         -> skip importing submodule branch into it
            metarepo_default_branch_tracks_submodule = (metarepo_tracked_branches is not None and metarepo_default_branch in metarepo_tracked_branches)
            branch_exists_in_metarepo = branch in metarepo_branches
            submodule_not_tracked_in_metarepo_branch = metarepo_tracked_branches is not None and branch not in metarepo_tracked_branches
            if (branch_exists_in_metarepo and submodule_not_tracked_in_metarepo_branch) or (not branch_exists_in_metarepo and not metarepo_default_branch_tracks_submodule):
                print(f"Skipping import of submodule {submodule_path} branch {branch} into monorepo, as metarepo branch does not track this submodule.")
                print(f"Details:")
                print(f"branch_exists_in_metarepo:                {branch_exists_in_metarepo}")
                print(f"submodule_not_tracked_in_metarepo_branch: {submodule_not_tracked_in_metarepo_branch}")
                print(f"metarepo_default_branch_tracks_submodule: {metarepo_default_branch_tracks_submodule}")
                print(f"")
                print(f"metarepo_tracked_branches: {metarepo_tracked_branches}")
                print(f"metarepo default_branch: {metarepo_default_branch}")
                continue

            # if some submodule doesn't contain a feature branch that DOES exist in the metarepo,
            # we should import the submodule's default branch into the metarepo's feature branch
            branch_to_import = branch
            if branch not in submodule_branches:
                if submodule_default_branch is None or submodule_default_branch not in submodule_branches:
                    raise RuntimeError(f"Cannot import submodule branch {branch} into monorepo, as it does not exist in the submodule, and default branch cannot be determined.")
                print(f"Submodule branch {branch} does not exist in submodule, using default branch {submodule_default_branch} instead.")
                branch_to_import = submodule_default_branch

            # if branch doesn't exist in the metarepo, we need to create it in the monorepo from the default branch
            if not branch_exists_in_metarepo:
                # first switch to the default branch
                exec_cmd(f"git switch {metarepo_default_branch}", cwd=monorepo_root_dir)
                # then create the new branch from it
                exec_cmd(f"git switch -c {branch}", cwd=monorepo_root_dir)
                print(f"Created new monorepo branch {branch} from metarepo default branch {metarepo_default_branch} to import submodule into it.")
            else:
                # branch exists in metarepo, so we should switch to it
                exec_cmd(f"git switch {branch}", cwd=monorepo_root_dir)
            print(header_string(f"Importing {submodule_path}:{branch_to_import} to monorepo:{branch}"))

            # Create a fresh clone of the submodule with just this branch
            branch_clone_dir_name = f"clone_{branch_to_import.replace('/', '_')}"
            branch_clone_dir = os.path.join(branches_dir, branch_clone_dir_name)
            exec_cmd(f"rm -rf {branch_clone_dir}") # might already exist if multiple metarepo branches point to same submodule branch
            exec_cmd(f"git clone -b {branch_to_import} --single-branch {submodule_repo_url} {branch_clone_dir}")

            # Run filter-repo on the isolated clone to move everything under submodule_path
            exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {submodule_path}", cwd=branch_clone_dir)
            
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
            exec_cmd(f"git merge {remote_name}/{branch_to_import} --allow-unrelated-histories -m 'Merge submodule {submodule_path} branch {branch_to_import} to monorepo branch {branch}'", cwd=monorepo_root_dir)
            
            # Cleanup remote (the clone directory will be cleaned up by tempdir)
            exec_cmd(f"git remote remove {remote_name}", cwd=monorepo_root_dir)

def get_metarepo_tracked_submodules_mapping(repo_path: str) -> Mapping[SubmoduleDef, Set[str]]:
    """
    Scans all branches in the given metarepo, and returns a mapping of submodules to the set of branches that track them.
    """
    tracked_submodules: Mapping[SubmoduleDef, Set[str]] = dict()
    branches = get_all_branches(repo_path)
    for branch in branches:
        print(f"--- Scanning branch {branch} for submodules ---")
        exec_cmd(f"git checkout {branch}", cwd=repo_path)
        submodules_in_branch = get_all_submodules(repo_path)
        for submodule in submodules_in_branch:
            if submodule not in tracked_submodules:
                tracked_submodules[submodule] = set()
            tracked_submodules[submodule].add(branch)
    return tracked_submodules

def main_flow(metarepo_url: str, monorepo_url: Optional[str] = None):
    ensure_dir(SANDBOX_DIR)
    # clone metarepo
    metarepo_root_dir = os.path.join(SANDBOX_DIR, "metarepo")
    exec_cmd(f"git clone {metarepo_url} metarepo", cwd=SANDBOX_DIR)
    
    # Determine metarepo default branch (after cloning, HEAD points to the default branch)
    metarepo_default_branch = get_head_branch(metarepo_root_dir)
    if metarepo_default_branch is None:
        raise RuntimeError(f"Cannot determine default branch of metarepo at {metarepo_root_dir}")
    print(f"Metarepo default branch: {metarepo_default_branch}")

    # Pull all branches locally to be able to discover them and their submodules
    metarepo_branches = update_all_repo_branches(metarepo_root_dir)

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
    metarepo_tracked_submodules_mapping = get_metarepo_tracked_submodules_mapping(metarepo_root_dir)

    print(f"Submodules to import:")
    for submodule in metarepo_tracked_submodules_mapping:
        print(f"path: {submodule.path}\nurl: {submodule.url}\n")
    
    # for each submodule, we will do a fresh clone, and then process it
    for submodule in metarepo_tracked_submodules_mapping:
        import_submodule(monorepo_root_dir, submodule.url, submodule.path, metarepo_default_branch, metarepo_branches, expected_branches=None, metarepo_tracked_branches=metarepo_tracked_submodules_mapping[submodule])

    print(header_string("Merge Complete"))

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
