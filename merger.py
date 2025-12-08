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

# Configurable paths
GIT_FILTER_REPO = os.path.join(os.path.expanduser("~"), "git-filter-repo")
THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DIR = os.path.join(THIS_SCRIPT_DIR, "sandbox")

# Ensure sandbox is removed at exit (optional: remove this in debug)
atexit.register(lambda: os.system(f"rm -rf {SANDBOX_DIR}"))

# ---------- Utility ----------
def exec_cmd(cmd: str, cwd: str | None = None, capture_output: bool = False) -> str | None:
    """
    Run shell command. Raises on non-zero exit.
    If capture_output is True, returns stdout (str).
    """
    print(f"Executing: {cmd} (cwd={cwd or os.getcwd()})")
    proc = subprocess.run(cmd, shell=True, cwd=cwd,
                          stdout=subprocess.PIPE if capture_output else None,
                          stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        err = proc.stderr.strip() if proc.stderr else "<no stderr>"
        raise RuntimeError(f"Command failed ({proc.returncode}): {cmd}\n{err}")
    return proc.stdout if capture_output else None

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

def get_all_branches(repo_path: str) -> List[str]:
    cmd = "git branch -a"
    out = exec_cmd(cmd, cwd=repo_path, capture_output=True)
    branches = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        line = line.strip()
        if line.find("HEAD") != -1:
            continue
        if line.startswith("remotes/origin/"):
            line = line[len("remotes/origin/"):]
        branches.add(line)
    return list(branches)

def get_all_branches_in_origin(url: str) -> List[str]:
    cmd = f"git ls-remote --heads {url}"
    out = exec_cmd(cmd, capture_output=True)
    branches = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])
    return branches

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

# ---------- Meta-repo import ----------
def import_meta_repo_all_branches(monorepo_root_dir: str, metarepo_url: str):
    """
    Clone the meta-repo once, then import each branch into the monorepo by fetching:
        git fetch <local_meta_clone> <branch>:refs/heads/<branch>
    This avoids merging or attempting to reconcile unrelated histories.
    """
    ensure_dir(SANDBOX_DIR)
    meta_name = "meta_repo"
    meta_clone = os.path.join(SANDBOX_DIR, meta_name)
    clone_repo_once(metarepo_url, meta_clone)

    branches = get_all_branches_in_origin(metarepo_url)
    print(f"Meta-repo branches: {branches}")

    # For each branch, fetch the meta branch directly into the monorepo as a new branch
    for branch in branches:
        print(f"=== Importing meta:{branch} ===")
        # ensure monorepo exists and branch created/overwritten to exactly meta branch
        # Fetch the branch into monorepo as a local branch named the same.
        exec_cmd(f"git fetch {meta_clone} refs/heads/{branch}:refs/heads/{branch}", cwd=monorepo_root_dir)
        # switch to it so later steps operate on branch
        exec_cmd(f"git switch {branch}", cwd=monorepo_root_dir)

# ---------- Subrepo import using one clone + worktrees ----------
def import_repo_all_branches(monorepo_root: str, repo_url: str, subdir: str):
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


# ---------- CLI ----------
def main():
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
