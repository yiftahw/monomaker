#!/usr/bin/env python3
from enum import Enum
import os
import argparse
import atexit
import configparser
import tempfile
from typing import Dict, List, Mapping, Optional, Set
from dataclasses import dataclass, field
import time
from models.repository import SubmoduleDef
from models.migration_report import MigrationImportInfo, MigrationReport, SubmoduleImportInfo
from utils import exec_cmd, header_string
import sys
import json

# Configurable paths
THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_FILTER_REPO = os.path.join(THIS_SCRIPT_DIR, "git-filter-repo")
SANDBOX_DIR = os.path.join(THIS_SCRIPT_DIR, "sandbox")

MONOMAKER_PREFIX = "[monomaker]"

# Global variables used for logging/reporting
metarepo_name = "metarepo"
monorepo_name = "monorepo"

if not os.path.exists(GIT_FILTER_REPO):
    raise RuntimeError(f"git-filter-repo not found at {GIT_FILTER_REPO}")

# Ensure sandbox is removed at exit (optional: remove this in debug)
atexit.register(lambda: os.system(f"rm -rf {SANDBOX_DIR}"))


@dataclass
class MonorepoCache:
    """
    Cache for expensive git operations on the monorepo.
    Avoids repeated calls to get_all_branches() and get_all_submodules().
    """
    monorepo_root_dir: str
    _branches: Optional[Set[str]] = field(default=None, repr=False)
    # Maps branch name -> list of submodules tracked in that branch
    _submodules_per_branch: Dict[str, List[SubmoduleDef]] = field(default_factory=dict, repr=False)
    # Tracks which branches have been scanned for submodules
    _scanned_branches: Set[str] = field(default_factory=set, repr=False)

    def get_branches(self, force_refresh: bool = False) -> Set[str]:
        """Get all branches in the monorepo (cached)."""
        if self._branches is None or force_refresh:
            self._branches = set(get_all_branches(self.monorepo_root_dir))
        return self._branches

    def add_branch(self, branch: str):
        """Register a newly created branch in the cache."""
        if self._branches is None:
            self._branches = set()
        self._branches.add(branch)

    def get_submodules_in_branch(self, branch: str, force_refresh: bool = False) -> List[SubmoduleDef]:
        """
        Get all submodules tracked in the given branch (cached).
        Will checkout the branch if not already on it.
        """
        if branch in self._scanned_branches and not force_refresh:
            return self._submodules_per_branch.get(branch, [])
        
        # Need to checkout and scan
        current_branch = get_head_branch(self.monorepo_root_dir)
        if current_branch != branch:
            exec_cmd(f"git checkout --recurse-submodules {branch}", cwd=self.monorepo_root_dir)
        
        submodules = get_all_submodules(self.monorepo_root_dir)
        self._submodules_per_branch[branch] = submodules
        self._scanned_branches.add(branch)
        
        # Clean up any uncommitted changes from submodule switching
        exec_cmd("git submodule update --checkout --force", cwd=self.monorepo_root_dir)
        
        return submodules

    def get_branches_tracking_submodule(self, submodule_path: str) -> Set[str]:
        """
        Get all branches that track the given submodule (uses cache).
        Ensures all known branches are scanned first.
        """
        branches = self.get_branches()
        current_branch = get_head_branch(self.monorepo_root_dir)
        
        # Scan any unscanned branches
        for branch in branches:
            if branch not in self._scanned_branches:
                self.get_submodules_in_branch(branch)
        
        # Restore original branch
        if current_branch is not None and current_branch != get_head_branch(self.monorepo_root_dir):
            exec_cmd(f"git checkout --recurse-submodules {current_branch}", cwd=self.monorepo_root_dir)
        
        # Find branches tracking this submodule
        tracking_branches = set()
        for branch, submodules in self._submodules_per_branch.items():
            for submodule in submodules:
                if submodule.path == submodule_path:
                    tracking_branches.add(branch)
                    break
        
        return tracking_branches

    def invalidate_branch_submodules(self, branch: str):
        """
        Invalidate the submodule cache for a specific branch.
        Call this after modifying submodules in a branch.
        """
        self._scanned_branches.discard(branch)
        self._submodules_per_branch.pop(branch, None)

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
    submodules: List[SubmoduleDef] = []
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


def get_head_commit(repo_path: str) -> str:
    """
    Returns the commit hash of the current HEAD in the given repo.
    """
    cmd = "git rev-parse HEAD"
    out = exec_cmd(cmd, cwd=repo_path)
    return out.stdout.strip()

def import_meta_repo(monorepo_root_dir: str, metarepo_root_dir: str):
    """
    It is expected that both folders are git repositories, and that the metarepo
    is already cloned locally.
    Returns a mapping of branch names to their metarepo commit hashes.
    """
    # we set up the metarepo as a remote of the monorepo, and we fetch all its branches.
    global metarepo_name
    print(header_string(f"Importing metarepo {metarepo_name} into monorepo {monorepo_name}"))
    metarepo_branches = get_all_branches(metarepo_root_dir)
    print(f"{metarepo_name} branches: {metarepo_branches}")
    exec_cmd(f"git remote add metarepo {metarepo_root_dir}", cwd=monorepo_root_dir)
    exec_cmd(f"git fetch metarepo '+refs/heads/*:refs/remotes/metarepo/*'", cwd=monorepo_root_dir)
    
    metarepo_branch_commits = dict()
    num_branches = len(metarepo_branches)
    for idx, branch in enumerate(metarepo_branches):
        print(f"=== [{idx+1}/{num_branches}] Importing {metarepo_name}:{branch} ===")
        # ensure monorepo exists and branch created/overwritten to exactly meta branch
        exec_cmd(f"git checkout -B {branch} metarepo/{branch}", cwd=monorepo_root_dir)
        # breadcrumb: commit message to indicate the first bookkeeping commit.
        commit_hash = get_head_commit(monorepo_root_dir)
        metarepo_branch_commits[branch] = commit_hash
        exec_cmd(f"git commit --allow-empty -m '{MONOMAKER_PREFIX} checkout `{metarepo_name}` branch `{branch}` at commit {commit_hash}'", cwd=monorepo_root_dir)
    # cleanup
    exec_cmd(f"git remote remove metarepo", cwd=monorepo_root_dir)
    return metarepo_branch_commits

def update_all_repo_branches(repo_root_dir: str):
    """
    Will fetch all branches from the origin, and update its local refs.  
    returns the list of all repo branches.
    """
    branches = get_all_branches(repo_root_dir)
    print(f"Updating all branches in repo at {repo_root_dir}: {branches}")
    
    # Single network call to fetch all branches at once
    exec_cmd("git fetch --all --prune", cwd=repo_root_dir)
    
    # Update local branches to match remote tracking branches (no network calls)
    current_branch = get_head_branch(repo_root_dir)
    num_branches = len(branches)
    for idx, branch in enumerate(branches):
        print(f"=== [{idx+1}/{num_branches}] Updating branch {branch} ===")
        if branch == current_branch:
            # Can't update checked-out branch with `git branch -f`, use reset instead
            exec_cmd(f"git reset --hard origin/{branch}", cwd=repo_root_dir)
        else:
            # Update branch ref directly without checkout
            exec_cmd(f"git branch -f {branch} origin/{branch}", cwd=repo_root_dir)
    return branches

def get_monorepo_branches_tracking_submodule(monorepo_root_dir: str, submodule_path: str, cache: MonorepoCache) -> Set[str]:
    """
    Get all branches in the monorepo that track the given submodule.
    Uses cached data to avoid repeated expensive git operations.
    """
    return cache.get_branches_tracking_submodule(submodule_path)

def import_submodule(monorepo_root_dir: str,
                     submodule_repo_url: str,
                     submodule_path: str,
                     metarepo_default_branch: str,
                     metarepo_branch_commits: Mapping[str, str],
                     cache: MonorepoCache,
                     expected_branches: Optional[Set[str]] = None) -> SubmoduleImportInfo:
    """
    It is expected that monorepo_root_dir points to a git repository where the submodule will be imported.
    the submodule will be cloned from submodule_repo_url, and all its branches will be imported under submodule_path in the monorepo.

    cache: MonorepoCache to avoid repeated expensive git operations.

    metarepo_branches_tracking_submodule: is only used for bookkeeping/reporting purposes, to know which metarepo branches actually tracked this submodule.
    """
    global monorepo_name, metarepo_name
    with tempfile.TemporaryDirectory() as tempdir:
        # First, make a full clone to serve as a local cache for all branches.
        # This avoids repeated network calls when cloning individual branches later.
        info_clone_dir = os.path.join(tempdir, "info_clone")
        print(header_string(f"Cloning submodule {submodule_path} from {submodule_repo_url} to get branch info ..."))
        exec_cmd(f"git clone {submodule_repo_url} {info_clone_dir}")
        exec_cmd("git fetch --all --prune", cwd=info_clone_dir)

        # Get the default branch (after cloning, HEAD points to the default branch)
        submodule_default_branch = get_head_branch(info_clone_dir)
        report = SubmoduleImportInfo(submodule_path, submodule_default_branch)

        # Get all branches from the fresh clone
        submodule_branches = set(get_all_branches(info_clone_dir))
        print(f"Found branches for submodule {submodule_path}: {submodule_branches}")
        if expected_branches is not None and submodule_branches != expected_branches:
            raise RuntimeError(f"Submodule branches mismatch. Expected: {expected_branches}, Found: {submodule_branches}")
        
        # Create local tracking branches for all remote branches so we can clone from this local repo.
        # git clone only sees local branches, not remote tracking refs.
        for branch in submodule_branches:
            if branch != submodule_default_branch:  # default branch already exists locally
                exec_cmd(f"git branch {branch} origin/{branch}", cwd=info_clone_dir, allow_failure=True)
        
        # Process each branch
        branches_dir = os.path.join(tempdir, "branches")
        ensure_dir(branches_dir)

        # Get branches from cache. The cache tracks newly created branches via add_branch(),
        # so subsequent submodule imports will see branches created by earlier imports.
        monorepo_branches = cache.get_branches()
        print(f"Found {len(monorepo_branches)} {monorepo_name} branches while importing submodule {submodule_path}:\n")
        print("\n".join(monorepo_branches))

        # from the available branches, we need to consider which ones track this submodule.
        # NOTE: all branches in the monorepo (either from metarepo or created in previous imports) are already available locally.
        monorepo_branches_tracking_submodule: Set[str] = get_monorepo_branches_tracking_submodule(monorepo_root_dir, submodule_path, cache)
        print(f"Found {len(monorepo_branches_tracking_submodule)} {monorepo_name} branches that actually track the submodule {submodule_path}:\n")

        # branches_closure: all branches that need to be considered for this submodule
        # see comments below for details
        branches_closure = monorepo_branches.union(submodule_branches)

        branches_to_skip = set()

        # Pre-create all needed branches that don't exist in the monorepo yet. (from the default)
        # This ensures that if multiple feature branches need to be created (case 4 below),
        # they all branch from the clean state of the metarepo default branch. 
        # (i.e before we might have populated it with this submodule's content)
        # TODO: create a unit-test for this scenario?
        for branch in branches_closure:
            branch_exists_in_monorepo = branch in monorepo_branches
            metarepo_default_branch_tracks_submodule = (metarepo_default_branch in monorepo_branches_tracking_submodule)
            submodule_not_tracked_in_metarepo_branch = branch not in monorepo_branches_tracking_submodule
            
            # Skip if this branch doesn't need to be processed
            if (branch_exists_in_monorepo and submodule_not_tracked_in_metarepo_branch) or (not branch_exists_in_monorepo and not metarepo_default_branch_tracks_submodule):
                branches_to_skip.add(branch)
                print(f"Skipping import of submodule {submodule_path} branch {branch} into {monorepo_name}, as {metarepo_name} branch does not track this submodule.")
                print(f"Details:")
                print(f"branch_exists_in_monorepo:                {branch_exists_in_monorepo}")
                print(f"submodule_not_tracked_in_metarepo_branch: {submodule_not_tracked_in_metarepo_branch}")
                print(f"metarepo_default_branch_tracks_submodule: {metarepo_default_branch_tracks_submodule}")
                print(f"")
                print(f"monorepo_branches_tracking_submodule: {monorepo_branches_tracking_submodule}")
                print(f"metarepo default_branch: {metarepo_default_branch}")
                continue
            
            # Create the branch if it doesn't exist
            # need to make sure it was not already created in the monorepo (in a previous submodule import)
            # recurse-submodules is needed because a simple `git switch` does not change the submodule HEADs if they are different between branches
            if branch not in monorepo_branches:
                exec_cmd(f"git switch --recurse-submodules {metarepo_default_branch}", cwd=monorepo_root_dir)
                exec_cmd(f"git switch -c {branch}", cwd=monorepo_root_dir)
                print(f"Pre-created {monorepo_name} branch {branch} from {metarepo_name} default branch {metarepo_default_branch}.")
                # Update monorepo_branches and cache to reflect the newly created branch
                monorepo_branches.add(branch)
                cache.add_branch(branch)
                branches_closure.add(branch)
        
        # Switch back to default branch after pre-creating branches
        exec_cmd(f"git switch --recurse-submodules {metarepo_default_branch}", cwd=monorepo_root_dir)

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

            # anything not tracked by git should be cleaned up here to avoid conflicts
            # if its not tracked by git, we probably don't want it in the monorepo anyway
            # this could happen if some submodule was not cleaned up properly in some tracking branch.
            # switching to this branch and then to another branch would leave uncommitted changes
            git_status_out = exec_cmd("git status --porcelain", cwd=monorepo_root_dir).stdout.strip()
            if git_status_out != "":
                print(f"Warning: cleaning uncommitted changes in {monorepo_name} at {monorepo_root_dir} before importing submodule {submodule_path} branch {branch} ...\n{git_status_out}")
                exec_cmd("git clean -fdX", cwd=monorepo_root_dir)
            
            # prepare monorepo branch
            # Switch to the branch (it should exist now, either existed in the metarepo or pre-created above)
            # Verify the branch exists - if not, it's a logic error
            if branch not in monorepo_branches:
                raise RuntimeError(f"Logic error: branch {branch} should exist in {monorepo_name} after preparation loop, but it doesn't. monorepo_branches: {monorepo_branches}")
            print(header_string(f"[{idx+1}/{num_branches}] Importing {submodule_path}:{branch_to_import} to {monorepo_name}:{branch}"))
            exec_cmd(f"git switch --recurse-submodules {branch}", cwd=monorepo_root_dir)

            # prepare submodule branch clone (isolated workspace, git-filter-repo modifies its git history)
            # Clone from local info_clone_dir using file:// protocol to avoid network overhead.
            # info_clone_dir already has all branches fetched, so this is purely local I/O.
            branch_clone_dir_name = f"clone_{branch_to_import.replace('/', '_')}"
            branch_clone_dir = os.path.join(branches_dir, branch_clone_dir_name)
            exec_cmd(f"rm -rf {branch_clone_dir}") # might already exist if multiple metarepo branches point to same submodule branch
            info_clone_abs = os.path.abspath(info_clone_dir)
            exec_cmd(f"git clone -b {branch_to_import} --single-branch file://{info_clone_abs} {branch_clone_dir}")
            submodule_branch_commit_hash = get_head_commit(branch_clone_dir)

            # Record in report
            # Determine which metarepo branch to use for the commit hash.
            # If this branch doesn't exist in metarepo (case 4: submodule-only branch),
            # use the metarepo default branch. We check metarepo_branch_commits directly
            # because monorepo_branches_tracking_submodule may include pre-created branches
            # that inherited submodule definitions from metarepo default.
            metarepo_branch_used = branch
            if branch not in metarepo_branch_commits:
                # case 4: submodule feature branch - use metarepo's default branch
                metarepo_branch_used = metarepo_default_branch
            
            # Get the metarepo commit hash from the mapping (captured during import_meta_repo)
            metarepo_commit_hash = metarepo_branch_commits[metarepo_branch_used]
            
            nested_submodules = get_all_submodules(branch_clone_dir)
            report.add_entry(branch, metarepo_branch_used, metarepo_commit_hash, branch_to_import, submodule_branch_commit_hash, nested_submodules)

            # Run filter-repo on the isolated clone to move everything under submodule_path
            exec_cmd(f"python3 {GIT_FILTER_REPO} --force --to-subdirectory-filter {submodule_path}", cwd=branch_clone_dir)
            
            # need to remove all the files in the monorepo that are under submodule_path
            submodule_full_path_in_monorepo = os.path.join(monorepo_root_dir, submodule_path)
            if os.path.exists(submodule_full_path_in_monorepo):
                print(f"Removing existing files in {monorepo_name} at {submodule_full_path_in_monorepo} ...")
                exec_cmd(f"git rm -rf {submodule_path}", cwd=monorepo_root_dir)
                exec_cmd(f"git commit -m '{MONOMAKER_PREFIX} remove submodule `{submodule_path}` from `{monorepo_name}`'", cwd=monorepo_root_dir)
            else:
                print(f"No existing files to remove in {monorepo_name} at {submodule_full_path_in_monorepo}.")

            # Add the filtered clone as a temporary remote, and merge its branch into the monorepo branch
            branch_clone_abs = os.path.abspath(branch_clone_dir)
            remote_name = f"tmp_{branch.replace('/', '_').replace('-', '_')}"
            
            exec_cmd(f"git remote add {remote_name} {branch_clone_abs}", cwd=monorepo_root_dir)
            exec_cmd(f"git fetch {remote_name}", cwd=monorepo_root_dir)
            exec_cmd(f"git merge {remote_name}/{branch_to_import} --allow-unrelated-histories -m '{MONOMAKER_PREFIX} merge submodule `{submodule_path}` branch `{branch_to_import}` at commit {submodule_branch_commit_hash}'", cwd=monorepo_root_dir)
            
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
                    exec_cmd(f"git commit -m '{MONOMAKER_PREFIX} remove .gitmodules in `{submodule_path}`'", cwd=monorepo_root_dir)
                # remove nested submodule entry from subdirectory
                nested_submodule_exists = os.path.exists(nested_submodule_abs_path)
                if nested_submodule_exists:
                    print(f"Removing nested submodule files at {nested_submodule_abs_path} ...")
                    exec_cmd(f"git rm -rf {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir)
                    exec_cmd(f"git commit -m '{MONOMAKER_PREFIX} remove submodule `{nested_submodule.path}` from `{submodule_path}`'", cwd=monorepo_root_dir)
                # re-register nested submodule in monorepo
                # `--force` is needed in case multiple branches contain the same nested submodule (likely)
                commit_hash = nested_submodule.commit_hash
                exec_cmd(f"git submodule add --force {nested_submodule.url} {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir)
                submodule_checkout_success = exec_cmd(f"git checkout {commit_hash}", cwd=nested_submodule_abs_path, allow_failure=True)
                if submodule_checkout_success.returncode != 0:
                    # grab actual commit hash from the submodule clone
                    new_commit_hash = get_head_commit(nested_submodule_abs_path)
                    print(f"Warning: cannot checkout commit {commit_hash} in nested submodule {nested_submodule_relative_path_in_monorepo}, using {new_commit_hash} instead.")
                    commit_hash = new_commit_hash
                else:
                    # git does not auto-stage the submodule checkout, so we need to do it manually
                    exec_cmd(f"git add {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir)
                exec_cmd(f"git commit -m '{MONOMAKER_PREFIX} add submodule `{nested_submodule_relative_path_in_monorepo}` at commit {commit_hash}'", cwd=monorepo_root_dir)
                # verify monorepo state is clean (nothing to commit, nothing staged)
                status_out = exec_cmd("git status --porcelain", cwd=monorepo_root_dir).stdout.strip()
                if status_out != "":
                    print(f"Warning: After adding nested submodule {nested_submodule_relative_path_in_monorepo}, {monorepo_name} repo is not clean:\n{status_out}")
                    # raise RuntimeError(f"After adding nested submodule {nested_submodule_relative_path_in_monorepo}, {monorepo_name} repo is not clean:\n{status_out}")
                # after submodule is commited, verify it's commit hash with `git ls-tree`
                ls_tree_out = exec_cmd(f"git ls-tree HEAD {nested_submodule_relative_path_in_monorepo}", cwd=monorepo_root_dir).stdout.strip().split()
                if len(ls_tree_out) < 3 or ls_tree_out[2] != commit_hash:
                    raise RuntimeError(f"After adding nested submodule {nested_submodule_relative_path_in_monorepo}, its commit hash in {monorepo_name} does not match expected {commit_hash}, got: {ls_tree_out}")
        return report

def get_metarepo_submodules(repo_path: str) -> Set[SubmoduleDef]:
    """
    Scans all branches in the given metarepo,  
    returns a mapping of {submodule -> set of branches that track them in the metarepo}.
    """
    branches = get_all_branches(repo_path)
    result = set()
    print(header_string("Scanning metarepo for submodules"))
    for branch in branches:
        print(f"--- Scanning branch {branch} for submodules ---")
        exec_cmd(f"git checkout {branch}", cwd=repo_path)
        submodules_in_branch = get_all_submodules(repo_path)
        result.update(set(submodules_in_branch))
    return result

@dataclass
class WorkspaceMetadata:
    monorepo_root_dir: str
    metarepo_root_dir: str
    metarepo_default_branch: str
    dump_template: bool = False
    template_path: Optional[str] = None

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
        if os.listdir(monorepo_root_dir):
            raise RuntimeError(f"Cannot create new empty monorepo at {monorepo_root_dir}, directory is not empty.")
        print(f"Creating a new empty repository at {monorepo_root_dir} ...")
        exec_cmd("git init --initial-branch=main", cwd=monorepo_root_dir, verbose_output=True)

    # Determine metarepo default branch (after cloning, HEAD points to the default branch)
    metarepo_default_branch = get_head_branch(metarepo_root_dir)
    if metarepo_default_branch is None:
        raise RuntimeError(f"Cannot determine default branch of {metarepo_name} at {metarepo_root_dir}")
    print(f"{metarepo_name} default branch: {metarepo_default_branch}")

    # Pull all branches locally to be able to discover them and their submodules
    update_all_repo_branches(metarepo_root_dir)

    return WorkspaceMetadata(
        monorepo_root_dir=monorepo_root_dir,
        metarepo_root_dir=metarepo_root_dir,
        metarepo_default_branch=metarepo_default_branch,
    )

@dataclass
class MigrationStrategyEntry:
    url: str
    consume_branches: bool
@dataclass
class MigrationStrategy:
    submodule_strategies: Mapping[str, MigrationStrategyEntry]

def main_flow(params: WorkspaceMetadata) -> MigrationImportInfo:
    # destructure params
    monorepo_root_dir = params.monorepo_root_dir
    metarepo_root_dir = params.metarepo_root_dir
    metarepo_default_branch = params.metarepo_default_branch

    global monorepo_name, metarepo_name
    report = MigrationImportInfo(metarepo_default_branch, metarepo_name, monorepo_name)

    # Import metarepo and get the mapping of branch names to their commit hashes
    metarepo_branch_commits = import_meta_repo(monorepo_root_dir, metarepo_root_dir)

    # Some branches in the metarepo may or may not track some submodules
    # So we need to scan all metarepo branches for submodules, to know which ones to import.
    # for each submodule, we will bookkeep which metarepo branches track it.
    metarepo_tracked_submodules = get_metarepo_submodules(metarepo_root_dir)

    if params.dump_template:
        output = dict()
        for submodule in metarepo_tracked_submodules:
            output[submodule.path] = {
                "url": submodule.url,
                "consume_branches": True
            }
        template_json = json.dumps(output, indent=4)
        template_path = params.template_path if params.template_path is not None else os.path.join(os.getcwd(), "migration_strategy.json")
        with open(template_path, "w") as f:
            f.write(template_json)
        print(f"Dumped migration strategy template to {template_path}. Exiting.")
        sys.exit(0)

    migration_strategy = MigrationStrategy(dict())
    if params.template_path is not None:
        print(f"Loading migration strategy from {params.template_path} ...")
        with open(params.template_path, "r") as f:
            strategy_json = f.read()
        strategy_dict: dict = json.loads(strategy_json)
        for submodule_path, entry_dict in strategy_dict.items():
            migration_strategy.submodule_strategies[submodule_path] = MigrationStrategyEntry(
                url=entry_dict["url"],
                consume_branches=entry_dict["consume_branches"]
            )

    def should_consume_submodule_branches(submodule: SubmoduleDef) -> bool:
        # if migration strategy doesn't contain submodule, assume happy path: consume all branches
        entry = migration_strategy.submodule_strategies.get(submodule.path)
        return entry is None or entry.consume_branches and entry.url == submodule.url

    print(f"Submodules to import:")
    for submodule in metarepo_tracked_submodules:
        print(f"path: {submodule.path}\nurl: {submodule.url}")
        if not should_consume_submodule_branches(submodule):
            print(f"  (will NOT consume branches from metarepo for this submodule, as per strategy)")
        print("")
    
    # Create cache for monorepo operations to avoid repeated expensive git calls
    monorepo_cache = MonorepoCache(monorepo_root_dir)
    
    # for each submodule, we will do a fresh clone, and then process it
    for submodule in metarepo_tracked_submodules:
        if not should_consume_submodule_branches(submodule):
            print(f"Skipping import of submodule {submodule.path} as per migration strategy.")
            continue
        submodule_report = import_submodule(monorepo_root_dir, submodule.url, submodule.path, metarepo_default_branch, metarepo_branch_commits, monorepo_cache)
        report.add_submodule_entry(submodule.path, submodule_report)

    # after all submodules are imported, we can iterate the branches and squash the bookkeeping commits.

    print(header_string("Merge Complete"))
    migration_report = MigrationReport(report)
    # JSON for machine-readable report
    with open(os.path.join(THIS_SCRIPT_DIR, "migration_report.json"), "w") as f:
        f.write(json.dumps(migration_report.as_dict(), indent=4))
    # Human-readable report
    with open(os.path.join(THIS_SCRIPT_DIR, "migration_report.txt"), "w") as f:
        f.write(str(migration_report))
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


def check_squashable(working_directory: str) -> bool:
    """
    Check whether the repository in the given working directory is squashable.
    
    Args:
        working_directory: Path to the working directory containing the repository.
        
    Returns:
        True if the repository is squashable, False otherwise.
    """
    print(header_string(f"Checking if repository at {working_directory} is squashable ..."))
    branches = get_all_branches(working_directory)
    num_branches = len(branches)
    current_branch = get_head_branch(working_directory)
    print(f"Found branches: {branches}")
    # squashable branches are branches where their commits containing the MONOMAKER_PREFIX
    # are contiguous in the commit history.
    class State(Enum):
        NOT_FOUND = 0
        FOUND_PREFIX = 1
        FOUND_NON_PREFIX = 2

    is_squashable = True
    for number, branch in enumerate(branches):
        # need to clean up local changes before running check out to avoid conflicts
        exec_cmd("git clean -fdx", cwd=working_directory, verbose=False)
        exec_cmd("git reset --hard", cwd=working_directory, verbose=False)
        exec_cmd(f"git checkout {branch}", cwd=working_directory, verbose=False)
        state = State.NOT_FOUND
        commit_log = exec_cmd("git log --pretty=format:%s", cwd=working_directory, verbose=False).stdout.strip().splitlines()
        for commit_msg in commit_log:
            if MONOMAKER_PREFIX in commit_msg:
                if state == State.NOT_FOUND:
                    state = State.FOUND_PREFIX
                elif state == State.FOUND_NON_PREFIX:
                    print(f"[{number+1}/{num_branches}] Branch {branch} is NOT squashable: found non-prefix commit followed by prefix commit: '{commit_msg}'")
                    is_squashable = False
                    break
            else:
                if state == State.FOUND_PREFIX:
                    state = State.FOUND_NON_PREFIX
        if state == State.NOT_FOUND:
            print(f"[{number+1}/{num_branches}] Branch {branch} has no monomaker commits, considered squashable.")
        elif is_squashable:
            print(f"[{number+1}/{num_branches}] Branch {branch} is squashable.")
        else:
            print(f"[{number+1}/{num_branches}] Branch {branch} is NOT squashable.")
    # finalize
    exec_cmd(f"git checkout {current_branch}", cwd=working_directory)
    return is_squashable
        


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
        "--dump-log",
        dest="dump_log",
        action="store_true",
        help="If set, saves the log output to a file named 'migration_log.txt' in the script directory."
    )
    parser.add_argument(
        "--dump-template",
        default=False,
        dest="dump_template",
        action="store_true",
        help="If set, dumps a strategy template file and exits."
    )
    parser.add_argument(
        "--template-path",
        dest="template_path",
        type=str,
        default=None,
        help="Path to save the strategy template file. If not provided, defaults to the current directory."
    )
    parser.add_argument(
        "--check-squashable",
        dest="check_squashable",
        action="store_true",
        help="If set, checks whether the repository is squashable."
    )
    args = parser.parse_args()
    if args.dump_log:
        # redirect stdout to a file
        log_txt_path = os.path.join(THIS_SCRIPT_DIR, "migration_log.txt")
        print(f"Dumping migration log to {log_txt_path} ...")
        log_file = open(log_txt_path, "w")
        sys.stdout = Tee(sys.stdout, log_file)
        sys.stderr = Tee(sys.stderr, log_file)
    
    # Handle --check-squashable mode
    if args.check_squashable:
        result = check_squashable(args.metarepo_url)
        sys.exit(0 if result else 1)
    
    print("start time:", time.ctime())
    workspace_params = prepare_workspace(args.metarepo_url, args.monorepo_url)
    workspace_params.dump_template = args.dump_template
    workspace_params.template_path = args.template_path
    migration_report = main_flow(workspace_params)
    end_time = time.monotonic()
    elapsed = end_time - start_time
    print(f"Total time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")

if __name__ == "__main__":
    main()
