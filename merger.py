#!/usr/bin/env python3
import os
import subprocess
import argparse
import atexit
from typing import List, Optional
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

def get_all_branches(repo_path: str, verbose: bool = False) -> List[str]:
    cmd = "git branch -a"
    out = exec_cmd(cmd, cwd=repo_path)
    branches = set()
    if verbose:
        print(f"Branches in repo {repo_path}:\n{out.stdout}")
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
    exec_cmd(f"git fetch metarepo", cwd=monorepo_root_dir)
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


def import_submodule(monorepo_root_dir: str, submodule_repo_url: str, submodule_path: str, expected_branches: set):
    """
    It is expected that both folders are git repositories, and that the submodule
    repo is already cloned locally.
    `submodule_path`: path inside the monorepo where the submodule content will be placed
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
        branches = set(get_all_branches(info_clone_dir, verbose=True))
        print(f"Found branches: {branches}")
        if branches != expected_branches:
            raise RuntimeError(f"Submodule branches mismatch. Expected: {expected_branches}, Found: {branches}")
        
        # Process each branch
        branches_dir = os.path.join(tempdir, "branches")
        ensure_dir(branches_dir)
        
        for branch in branches:
            print(f"====================================")
            print(f"=== Importing submodule:{branch} ===")
            print(f"====================================")
            
            # Create a fresh clone of just this branch
            branch_clone_dir = os.path.join(branches_dir, f"clone_{branch.replace('/', '_')}")
            exec_cmd(f"git clone -b {branch} --single-branch {submodule_repo_url} {branch_clone_dir}")

            files_in_submodule_branch = os.listdir(branch_clone_dir)
            print(f"\n\n\nSubmodule branch '{branch}' files before filter-repo: {files_in_submodule_branch}")
            
            # Run filter-repo on the isolated clone to move everything under submodule_path
            exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {submodule_path}", cwd=branch_clone_dir)
            
            # after filter-repo, files are moved to be relative to `submodule_path`
            files_after_filter = os.listdir(os.path.join(branch_clone_dir, submodule_path))
            print(f"\n\n\nSubmodule branch '{branch}' files after filter-repo: {files_after_filter}")

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
            
            # print files in monorepo submodule path after merge
            monorepo_files_after_merge = listdir_list(monorepo_root_dir)
            debug_print = pretty_print_list(monorepo_files_after_merge)
            print(f"\n\n\nMonorepo files after merging submodule branch '{branch}':\n{debug_print}\n\n\n")

            # Cleanup remote (the clone directory will be cleaned up by tempdir)
            exec_cmd(f"git remote remove {remote_name}", cwd=monorepo_root_dir)



def main_flow(metarepo_url: str, monorepo_url: Optional[str] = None):
    # clone metarepo
    metarepo_root_dir = os.path.join(SANDBOX_DIR, "metarepo")
    exec_cmd(f"git clone {metarepo_url} metarepo", cwd=SANDBOX_DIR)

    # Prepare monorepo
    monorepo_root_dir = os.path.join(SANDBOX_DIR, "monorepo")
    if monorepo_url:
        exec_cmd(f"git clone {monorepo_url} monorepo", cwd=SANDBOX_DIR)
    else:
        ensure_dir(monorepo_root_dir)
        print(f"Creating a new empty repository at {monorepo_root_dir} ...")
        exec_cmd("git init --initial-branch=main", cwd=monorepo_root_dir, verbose_output=True)

    # Import metarepo
    import_meta_repo(monorepo_root_dir, metarepo_root_dir)

    # Import all submodules
    submodules = get_all_submodules(metarepo_root_dir)
    for submodule in submodules:
        submodule_path_in_metarepo = os.path.join(metarepo_root_dir, submodule.path)
        expected_branches = set(get_all_branches(submodule_path_in_metarepo))
        import_submodule(monorepo_root_dir, submodule.url, submodule.path, expected_branches)

    # Cleanup: remove metarepo clone
    os.system(f"rm -rf {metarepo_root_dir}")


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
