#!/usr/bin/env python3
import os
import subprocess
import argparse
import atexit
from typing import List
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

# ---------- Repo helpers ----------
def create_empty_repo(path: str):
    ensure_dir(path)
    exec_cmd("git init", cwd=path)

def clone_repo_once(repo_url: str, local_dir: str):
    """
    Clone the repo once into local_dir if not present. Uses --no-checkout so we can
    create worktrees cheaply.
    """
    if os.path.exists(local_dir):
        # fetch/refresh
        exec_cmd("git fetch --all --prune", cwd=local_dir)
        return local_dir

    ensure_dir(os.path.dirname(local_dir))
    exec_cmd(f"git clone --no-checkout {repo_url} {local_dir}")
    # ensure we have all branches
    exec_cmd("git fetch --all --prune", cwd=local_dir)
    return local_dir

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

# ---------- Subrepo import using one clone + worktrees ----------
def import_repo_all_branches(monorepo_root: str, repo_url: str, subdir: str):
    return # TODO: re-implement later
    """
    Clone the repo once into SANDBOX_DIR/<subdir>_baseclone, create a worktree for
    each branch, run git-filter-repo inside the worktree (destructive only to worktree),
    and then fetch the rewritten branch into the monorepo as an identical branch.
    """
    ensure_dir(SANDBOX_DIR)
    base_clone = os.path.join(SANDBOX_DIR, f"{subdir}_baseclone")
    worktrees_root = os.path.join(SANDBOX_DIR, f"{subdir}_worktrees")
    ensure_dir(worktrees_root)

    clone_repo_once(repo_url, base_clone)

    # gather branches from remote (origin)
    branches = get_all_branches_in_origin(repo_url)
    print(f"{subdir} branches: {branches}")

    for branch in branches:
        print(f"=== Importing {subdir}:{branch} ===")
        worktree_dir = os.path.join(worktrees_root, branch)
        # ensure any previous worktree removed
        if os.path.exists(worktree_dir):
            exec_cmd(f"rm -rf {worktree_dir}")

        # create worktree pointing to origin/<branch>
        exec_cmd(f"git worktree add {worktree_dir} origin/{branch}", cwd=base_clone)

        # run filter-repo inside the worktree; this mutates the worktree repo only
        # (must have GIT_FILTER_REPO available and executable)
        if not os.path.exists(GIT_FILTER_REPO):
            raise RuntimeError(f"git-filter-repo not found at {GIT_FILTER_REPO}")
        exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {subdir}", cwd=worktree_dir)

        # fetch the rewritten branch into the monorepo as a branch with the same name
        # (this sets monorepo branch to exactly the rewritten worktree branch)
        exec_cmd(f"git fetch {worktree_dir} refs/heads/{branch}:refs/heads/{branch}", cwd=monorepo_root)

        # cleanup worktree
        exec_cmd(f"git worktree remove --force {worktree_dir}", cwd=base_clone)

    # optional: remove the local base clone if you don't want to keep it
    # exec_cmd(f"rm -rf {base_clone}")
    # exec_cmd(f"rm -rf {worktrees_root}")

# ---------- Monorepo creation / validation ----------
def clone_and_validate_monorepo(monorepo_url: str, repo_path: str):
    return # TODO: re-implement later
    print(f"Cloning monorepo from {monorepo_url} into {repo_path} ...")
    if os.path.exists(repo_path):
        raise Exception(f"Directory {repo_path} already exists. Please remove it first.")
    exec_cmd(f"git clone {monorepo_url} {repo_path}")
    allowed_files = {'.git', 'README.md', 'README', '.gitignore', '.gitattributes'}
    actual_files = set(os.listdir(repo_path))
    unexpected_files = actual_files - allowed_files
    if unexpected_files:
        raise Exception(f"Monorepo is not empty. Found unexpected files: {', '.join(unexpected_files)}.")
    print("Monorepo validated as empty.")

def merge_repositories(config: Config):
    return # TODO: re-implement later
    repo_path = os.path.join(THIS_SCRIPT_DIR, config.destination.path) if config.destination else os.path.join(THIS_SCRIPT_DIR, "monorepo")
    # prepare monorepo
    if config.destination and getattr(config.destination, "url", None):
        clone_and_validate_monorepo(config.destination.url, repo_path)
    else:
        create_empty_repo(repo_path)

    # Import meta branches (fetch into monorepo as-is)
    import_meta_repo_all_branches(repo_path, config.metarepo.url)

    # Now import each subrepo; each branch will be fetched into monorepo as-is
    for repo in config.repositories:
        import_repo_all_branches(repo_path, repo.url, repo.path)


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
        exec_cmd(f"git clone {submodule_repo_url} {info_clone_dir}") # exec_cmd(f"git clone --bare {submodule_repo_url} {info_clone_dir}")
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


"""
def import_repo_branch(monorepo_root: str, repo_url: str, branch: str, subdirectory: str):
    # clone the submodule as a temporary repo
    subdirectory_dir = os.path.join(SANDBOX_DIR, subdirectory)
    subdirectory_clone_parent = os.path.dirname(subdirectory_dir)
    os.makedirs(subdirectory_clone_parent, exist_ok=True)
    
    # clone the repo to sandbox
    os.chdir(subdirectory_clone_parent)
    exec_cmd(f"git clone -b {branch} {repo_url} {subdirectory}")
    
    # rewrite its history to be in a subdirectory with its name
    os.chdir(subdirectory_dir)
    exec_cmd(f"python3 {GIT_FILTER_REPO} --to-subdirectory-filter {subdirectory}")
    
    # merge the rewritten repo history into the monorepo
    os.chdir(monorepo_root)
    exec_cmd(f"git remote add {subdirectory} {subdirectory_dir}")
    exec_cmd(f"git fetch {subdirectory}")
    exec_cmd(f"git merge {subdirectory}/{branch} --allow-unrelated-histories -m 'Merge {subdirectory}/{branch} into monorepo'")
    
    # cleanup
    exec_cmd(f"git remote remove {subdirectory}")
    exec_cmd(f"rm -rf {subdirectory_dir}")
"""


def import_submodule_with_clone(monorepo_root_dir: str, submodule_repo_url: str, submodule_path: str):
    pass

# ---------- CLI ----------
def main():
    return #
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    b = subparsers.add_parser("branch-report", aliases=["b"])
    b.add_argument("-o", "--output", default=None)

    m = subparsers.add_parser("merge", aliases=["m"])

    s = subparsers.add_parser("submodule-report", aliases=["s"])
    s.add_argument("-o", "--output", default=None)

    args = parser.parse_args()

    # load config.json from current dir
    try:
        with open("config.json", "r") as f:
            config = Config.from_json(f.read())
    except Exception as e:
        print("Failed to load config.json:", e)
        return

    if args.command in ["branch-report", "b"]:
        # same logic as before (not included here for brevity)
        report = []
        report.append({"url": config.metarepo.url, "branches": get_all_branches_in_origin(config.metarepo.url)})
        for r in config.repositories:
            report.append({"url": r.url, "branches": get_all_branches_in_origin(r.url)})
        if args.output:
            with open(args.output, "w") as fo:
                fo.write(json.dumps(report, indent=2))
            print("Wrote branch report to", args.output)
        else:
            pprint(report)
    elif args.command in ["merge", "m"]:
        merge_repositories(config)
    elif args.command in ["submodule-report", "s"]:
        pass

if __name__ == "__main__":
    main()
