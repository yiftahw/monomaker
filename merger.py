#!/usr/bin/env python3
import os
import argparse
import atexit
import configparser
import tempfile
from typing import List, Mapping, Optional, Set
from dataclasses import dataclass
import time
from models.repository import SubmoduleDef
from models.migration_report import MigrationImportInfo, SubmoduleImportInfo
from utils import exec_cmd, header_string
import sys

# Configurable paths
THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_FILTER_REPO = os.path.join(THIS_SCRIPT_DIR, "git-filter-repo")
SANDBOX_DIR = os.path.join(THIS_SCRIPT_DIR, "sandbox")

# Global variables used for logging/reporting
metarepo_name = "metarepo"
monorepo_name = "monorepo"

if not os.path.exists(GIT_FILTER_REPO):
    raise RuntimeError(f"git-filter-repo not found at {GIT_FILTER_REPO}")

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
    if default_branch == "HEAD" or default_branch.find("no branch") != -1 or default_branch == "":
        return None
    return default_branch


def get_all_submodules(repo_path: str) -> List[SubmoduleDef]:
    """
    Returns list of submodule paths in the given repo (at its current HEAD)
    """
    # retrieve all submodule commit hashes
    # git submodule status is not recursive, which is good for us
    submodule_hashes_raw = exec_cmd("git submodule status", cwd=repo_path, allow_failure=True)
    if submodule_hashes_raw.returncode != 0 and submodule_hashes_raw.stderr:
        print(f"Warning: git submodule status failed in repo at {repo_path}, some submodules may be missing. Error: {submodule_hashes_raw.stderr}")
    submodule_hashes = dict()
    for line in submodule_hashes_raw.stdout.splitlines():
        line = line.strip()
        if line == "":
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        commit_hash = parts[0].lstrip("-+")
        path = parts[1]
        submodule_hashes[path] = commit_hash

    # read .gitmodules file to get the submodule paths and URLs
    gitmodules_path = os.path.join(repo_path, ".gitmodules")
    if not os.path.isfile(gitmodules_path):
        return []
    config = configparser.ConfigParser()
    config.read(gitmodules_path)
    submodules = []
    for section in config.sections():
        if section.startswith("submodule "):
            path = config[section].get("path")
            if not path:
                continue
            url = config[section].get("url")
            if not url:
                continue
            commit_hash = submodule_hashes.get(path, "")
            if commit_hash == "":
                print(f"WARNING: Cannot find commit hash for submodule at path {path}, skipping it.")
            else:
                submodules.append(SubmoduleDef(path, url, commit_hash))
    return submodules


def import_meta_repo(monorepo_root_dir: str, metarepo_root_dir: str):
    """
    It is expected that both folders are git repositories, and that the metarepo
    is already cloned locally.
    """
    global metarepo_name
    metarepo_branches = get_all_branches(metarepo_root_dir)
    print(f"{metarepo_name} branches: {metarepo_branches}")
    exec_cmd(f"git remote add metarepo {metarepo_root_dir}", cwd=monorepo_root_dir)
    exec_cmd(f"git fetch metarepo '+refs/heads/*:refs/remotes/metarepo/*'", cwd=monorepo_root_dir)
    num_branches = len(metarepo_branches)
    for idx, branch in enumerate(metarepo_branches):
        print(f"=== [{idx+1}/{num_branches}] Importing {metarepo_name}:{branch} ===")
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
    num_branches = len(branches)
    for idx, branch in enumerate(branches):
        print(f"=== [{idx+1}/{num_branches}] Updating branch {branch} ===")
        exec_cmd(f"git checkout {branch}", cwd=repo_root_dir)
        exec_cmd(f"git pull origin {branch}", cwd=repo_root_dir)
    return branches

def import_submodule(monorepo_root_dir: str,
                     submodule_repo_url: str,
                     submodule_path: str,
                     metarepo_default_branch: str,
                     metarepo_branches: Set[str],
                     expected_branches: Optional[Set[str]] = None,
                     metarepo_tracked_branches: Optional[Set[str]] = None) -> SubmoduleImportInfo:
    """
    It is expected that monorepo_root_dir points to a git repository where the submodule will be imported.
    the submodule will be cloned from submodule_repo_url, and all its branches will be imported under submodule_path in the monorepo.

    metarepo_tracked_branches: all branches in the metarepo that track this submodule.
    """
    global monorepo_name, metarepo_name
    report = SubmoduleImportInfo(submodule_path)
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
        # see comments below for details
        branches_closure = submodule_branches.copy()
        if metarepo_tracked_branches is not None:
            branches_closure.update(metarepo_tracked_branches)

        monorepo_branches = set(get_all_branches(monorepo_root_dir))
        print(f"Found {monorepo_name} branches while importing submodule {submodule_path}:\n")
        print("\n".join(monorepo_branches))
        branches_to_skip = set()

        # Pre-create all needed branches that don't exist in metarepo yet
        # This ensures that if multiple feature branches need to be created (case 4 below),
        # they all branch from the clean metarepo default branch, not from a branch
        # that already has submodule content imported into it
        # TODO: create a unit-test for this scenario?
        for branch in branches_closure:
            branch_exists_in_metarepo = branch in metarepo_branches
            metarepo_default_branch_tracks_submodule = (metarepo_tracked_branches is not None and metarepo_default_branch in metarepo_tracked_branches)
            submodule_not_tracked_in_metarepo_branch = metarepo_tracked_branches is not None and branch not in metarepo_tracked_branches
            
            # Skip if this branch doesn't need to be processed
            if (branch_exists_in_metarepo and submodule_not_tracked_in_metarepo_branch) or (not branch_exists_in_metarepo and not metarepo_default_branch_tracks_submodule):
                branches_to_skip.add(branch)
                print(f"Skipping import of submodule {submodule_path} branch {branch} into {monorepo_name}, as {metarepo_name} branch does not track this submodule.")
                print(f"Details:")
                print(f"branch_exists_in_metarepo:                {branch_exists_in_metarepo}")
                print(f"submodule_not_tracked_in_metarepo_branch: {submodule_not_tracked_in_metarepo_branch}")
                print(f"metarepo_default_branch_tracks_submodule: {metarepo_default_branch_tracks_submodule}")
                print(f"")
                print(f"metarepo_tracked_branches: {metarepo_tracked_branches}")
                print(f"metarepo default_branch: {metarepo_default_branch}")
                continue
            
            # Create the branch if it doesn't exist
            # need to make sure it was not already created in the monorepo (in a previous submodule import)
            if branch not in monorepo_branches:
                exec_cmd(f"git switch {metarepo_default_branch}", cwd=monorepo_root_dir)
                exec_cmd(f"git switch -c {branch}", cwd=monorepo_root_dir)
                print(f"Pre-created {monorepo_name} branch {branch} from {metarepo_name} default branch {metarepo_default_branch}.")
                # Update monorepo_branches to reflect the newly created branch
                monorepo_branches.add(branch)
        
        # Switch back to default branch after pre-creating branches
        exec_cmd(f"git switch {metarepo_default_branch}", cwd=monorepo_root_dir)

        num_branches = len(branches_closure)
        for idx, branch in enumerate(branches_closure):
            # for each {metarepo/branch}, if:
            # 1. branch exists in metarepo but doesn't track submodule -> skip importing submodule branch into it
            # 2. branch exists in metarepo, exists in submodule        -> import submodule branch into it (if submodule is tracked in the metarepo branch)
            # 3. branch exists in metarepo, doesn't exist in submodule -> import the submodule's default branch (if needed, see above)
            # 4. branch doesn't exist in metarepo, exists in submodule -> branch out from metarepo's default branch, import the submodule (if needed, see above)
            
            # NOTE: in case 4, it is assumed that the metarepo itself was already imported into the monorepo,
            # so the default branch should exist fully in the monorepo, and it is safe to branch out from it.

            # case 1: branch exists in metarepo but doesn't track submodule, or doesn't exist and default branch doesn't track it either
            #         -> skip importing submodule branch into it (we can't retest this logic as we pre-created needed branches above)
            if (branch in branches_to_skip):
                continue

            # if some submodule doesn't contain a feature branch that DOES exist in the metarepo,
            # we should import the submodule's default branch into the metarepo's feature branch
            branch_to_import = branch
            if branch not in submodule_branches:
                if submodule_default_branch is None or submodule_default_branch not in submodule_branches:
                    raise RuntimeError(f"Cannot import submodule branch {branch} into {monorepo_name}, as it does not exist in the submodule, and its default branch cannot be determined.")
                print(f"Branch {branch} does not exist in submodule, using default branch {submodule_default_branch} instead.")
                branch_to_import = submodule_default_branch

            # prepare monorepo branch
            # Switch to the branch (it should exist now, either from metarepo or pre-created above)
            # Verify the branch exists - if not, it's a logic error
            if branch not in monorepo_branches:
                raise RuntimeError(f"Logic error: branch {branch} should exist in {monorepo_name} after preparation loop, but it doesn't. monorepo_branches: {monorepo_branches}")
            metarepo_branch_used = branch
            exec_cmd(f"git switch {branch}", cwd=monorepo_root_dir)
            print(header_string(f"[{idx+1}/{num_branches}] Importing {submodule_path}:{branch_to_import} to {monorepo_name}:{branch}"))

            # prepare submodule branch clone (isolated workspace, git-filter-repo modifies its git history)
            branch_clone_dir_name = f"clone_{branch_to_import.replace('/', '_')}"
            branch_clone_dir = os.path.join(branches_dir, branch_clone_dir_name)
            exec_cmd(f"rm -rf {branch_clone_dir}") # might already exist if multiple metarepo branches point to same submodule branch
            exec_cmd(f"git clone -b {branch_to_import} --single-branch {submodule_repo_url} {branch_clone_dir}")

            # Record in report
            nested_submodules = get_all_submodules(branch_clone_dir)
            report.add_entry(branch, metarepo_branch_used, branch_to_import, nested_submodules)

            # Run filter-repo on the isolated clone to move everything under submodule_path
            exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {submodule_path}", cwd=branch_clone_dir)
            
            # need to remove all the files in the monorepo that are under submodule_path
            submodule_full_path_in_monorepo = os.path.join(monorepo_root_dir, submodule_path)
            if os.path.exists(submodule_full_path_in_monorepo):
                print(f"Removing existing files in {monorepo_name} at {submodule_full_path_in_monorepo} ...")
                exec_cmd(f"git rm -rf {submodule_path}", cwd=monorepo_root_dir)
                exec_cmd(f"git commit -m 'Remove submodule {submodule_path} before merging to {monorepo_name}'", cwd=monorepo_root_dir)
            else:
                print(f"No existing files to remove in {monorepo_name} at {submodule_full_path_in_monorepo}.")

            # Add the filtered clone as a temporary remote, and merge its branch into the monorepo branch
            branch_clone_abs = os.path.abspath(branch_clone_dir)
            remote_name = f"tmp_{branch.replace('/', '_').replace('-', '_')}"
            
            exec_cmd(f"git remote add {remote_name} {branch_clone_abs}", cwd=monorepo_root_dir)
            exec_cmd(f"git fetch {remote_name}", cwd=monorepo_root_dir)
            exec_cmd(f"git merge {remote_name}/{branch_to_import} --allow-unrelated-histories -m 'Merge submodule {submodule_path} branch {branch_to_import} to {monorepo_name} branch {branch}'", cwd=monorepo_root_dir)
            
            # Cleanup remote (the clone directory will be cleaned up by tempdir)
            exec_cmd(f"git remote remove {remote_name}", cwd=monorepo_root_dir)

            # if we found any nested submodules in this submodule, we need to remove `submodule_path/.gitmodules` file from the monorepo
            # and then register the actual nested submodules in the monorepo
            for nested_submodule in nested_submodules:
                nested_submodule_relative_path_in_monorepo = os.path.join(submodule_path, nested_submodule.path)
                nested_submodule_abs_path = os.path.join(monorepo_root_dir, nested_submodule_relative_path_in_monorepo)
                print(header_string(f"Registering nested submodule {nested_submodule_relative_path_in_monorepo} in {monorepo_name} branch {branch}"))
                # remove .gitmodules file if it exists
                gitmodules_in_monorepo = os.path.join(monorepo_root_dir, submodule_path, ".gitmodules")
                if os.path.isfile(gitmodules_in_monorepo): # if we have more than one nested submodule in the same subdirectory, we only need to remove it once
                    print(f"Removing .gitmodules file for nested submodules at {gitmodules_in_monorepo} ...")
                    exec_cmd(f"git rm {os.path.join(submodule_path, '.gitmodules')}", cwd=monorepo_root_dir)
                    exec_cmd(f"git commit -m 'Remove .gitmodules in {submodule_path}'", cwd=monorepo_root_dir)
                # remove nested submodule entry from subdirectory
                nested_submodule_exists = os.path.exists(nested_submodule_abs_path)
                if nested_submodule_exists:
                    print(f"Removing nested submodule files at {nested_submodule_abs_path} ...")
                    exec_cmd(f"git rm -rf {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir)
                    exec_cmd(f"git commit -m 'Remove nested submodule {nested_submodule_relative_path_in_monorepo} before re-tracking in {monorepo_name}'", cwd=monorepo_root_dir)
                # re-register nested submodule in monorepo
                # `--force` is needed in case multiple branches contain the same nested submodule (likely)
                commit_hash = nested_submodule.commit_hash
                exec_cmd(f"git submodule add --force {nested_submodule.url} {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir)
                submodule_checkout_success = exec_cmd(f"git checkout {commit_hash}", cwd=nested_submodule_abs_path, allow_failure=True)
                if not submodule_checkout_success.returncode == 0:
                    # grab actual commit hash from the submodule clone
                    new_commit_hash = exec_cmd("git rev-parse HEAD", cwd=nested_submodule_abs_path).stdout.strip()
                    print(f"Warning: cannot checkout commit {commit_hash} in nested submodule {nested_submodule_relative_path_in_monorepo}, using {new_commit_hash} instead.")
                    commit_hash = new_commit_hash
                exec_cmd(f"git commit -m 'Add nested submodule {nested_submodule_relative_path_in_monorepo} at commit {commit_hash}'", cwd=monorepo_root_dir)
                
    return report

def get_metarepo_tracked_submodules_mapping(repo_path: str) -> Mapping[SubmoduleDef, Set[str]]:
    """
    Scans all branches in the given metarepo,  
    returns a mapping of {submodule -> set of branches that track them in the metarepo}.
    """
    tracked_submodules: Mapping[SubmoduleDef, Set[str]] = dict()
    branches = get_all_branches(repo_path)
    for branch in branches:
        print(f"--- Scanning branch {branch} for submodules ---")
        exec_cmd(f"git checkout {branch}", cwd=repo_path)
        submodules_in_branch = get_all_submodules(repo_path)
        for submodule in submodules_in_branch:
            # ignore commit hash for tracking purposes, 
            # as we only care here about the existence (or lack) of a submodule in the branch.
            # TODO: find a cleaner solution for this?
            submodule.commit_hash = ""
            if submodule not in tracked_submodules:
                tracked_submodules[submodule] = set()
            tracked_submodules[submodule].add(branch)
    return tracked_submodules

@dataclass
class WorkspaceMetadata:
    monorepo_root_dir: str
    metarepo_root_dir: str
    metarepo_default_branch: str
    metarepo_branches: List[str]

def extract_repo_name_from_url(repo_url: str, default: str) -> str:
    default_is_bad = default is None or len(default) == 0
    # remove .git suffix if exists
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]
    # extract last part after /
    extracted = repo_url.split("/")[-1]
    if extracted == "":
        if default_is_bad:
            raise RuntimeError(f"Cannot extract repository name from URL '{repo_url}', and no default provided.")
        return default
    return extracted

def prepare_workspace(metarepo_url: str, monorepo_url: Optional[str] = None):
    global metarepo_name, monorepo_name
    metarepo_name = extract_repo_name_from_url(metarepo_url, "metarepo")
    monorepo_name = extract_repo_name_from_url(monorepo_url, "monorepo") if monorepo_url else "monorepo"

    ensure_dir(SANDBOX_DIR)

    # prepare metarepo
    metarepo_root_dir = os.path.join(SANDBOX_DIR, metarepo_name)
    exec_cmd(f"git clone {metarepo_url} {metarepo_name}", cwd=SANDBOX_DIR)

    # Prepare monorepo
    monorepo_root_dir = os.path.join(THIS_SCRIPT_DIR, monorepo_name) # TODO: allow user to choose where to create it on disk
    if monorepo_url:
        exec_cmd(f"git clone {monorepo_url} {monorepo_name}", cwd=THIS_SCRIPT_DIR)
    else:
        ensure_dir(monorepo_root_dir)
        print(f"Creating a new empty repository at {monorepo_root_dir} ...")
        exec_cmd("git init --initial-branch=main", cwd=monorepo_root_dir, verbose_output=True)

    # Determine metarepo default branch (after cloning, HEAD points to the default branch)
    metarepo_default_branch = get_head_branch(metarepo_root_dir)
    if metarepo_default_branch is None:
        raise RuntimeError(f"Cannot determine default branch of {metarepo_name} at {metarepo_root_dir}")
    print(f"{metarepo_name} default branch: {metarepo_default_branch}")

    # Pull all branches locally to be able to discover them and their submodules
    metarepo_branches = update_all_repo_branches(metarepo_root_dir)

    return WorkspaceMetadata(
        monorepo_root_dir=monorepo_root_dir,
        metarepo_root_dir=metarepo_root_dir,
        metarepo_default_branch=metarepo_default_branch,
        metarepo_branches=metarepo_branches
    )


def main_flow(params: WorkspaceMetadata) -> MigrationImportInfo:
    global monorepo_name, metarepo_name
    report = MigrationImportInfo(metarepo_name, monorepo_name)

    # destructure params
    monorepo_root_dir = params.monorepo_root_dir
    metarepo_root_dir = params.metarepo_root_dir
    metarepo_default_branch = params.metarepo_default_branch
    metarepo_branches = params.metarepo_branches

    # Import metarepo
    import_meta_repo(monorepo_root_dir, metarepo_root_dir)

    # Some branches in the metarepo may or may not track some submodules
    # So we need to scan all metarepo branches for submodules, to know which ones to import.
    # for each submodule, we will bookkeep which metarepo branches track it.
    metarepo_tracked_submodules_mapping = get_metarepo_tracked_submodules_mapping(metarepo_root_dir)

    print(f"Submodules to import:")
    for submodule in metarepo_tracked_submodules_mapping:
        print(f"path: {submodule.path}\nurl: {submodule.url}\n")
    
    # for each submodule, we will do a fresh clone, and then process it
    for submodule in metarepo_tracked_submodules_mapping:
        submodule_report = import_submodule(monorepo_root_dir, submodule.url, submodule.path, metarepo_default_branch, set(metarepo_branches), expected_branches=None, metarepo_tracked_branches=metarepo_tracked_submodules_mapping[submodule])
        report.add_submodule_entry(submodule.path, submodule_report)

    print(header_string("Merge Complete"))
    return report

class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()

# ---------- CLI ----------
def main():
    start_time = time.monotonic()
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
    parser.add_argument(
        "--dump-txt",
        dest="dump_txt",
        action="store_true",
        help="If set, dumps the migration report to a text file."
    )
    args = parser.parse_args()
    if args.dump_txt:
        # redirect stdout to a file
        report_txt_path = os.path.join(THIS_SCRIPT_DIR, "migration_report.txt")
        print(f"Dumping migration report to {report_txt_path} ...")
        log_file = open(report_txt_path, "w")
        sys.stdout = Tee(sys.stdout, log_file)
        sys.stderr = Tee(sys.stderr, log_file)
    print("start time:", time.ctime())
    workspace_params = prepare_workspace(args.metarepo_url, args.monorepo_url)
    migration_report = main_flow(workspace_params)
    print(migration_report)
    end_time = time.monotonic()
    elapsed = end_time - start_time
    print(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")

if __name__ == "__main__":
    main()
