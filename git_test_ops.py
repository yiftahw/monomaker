"""
Simple API for Git operations.
"""
import os
from utils import exec_cmd, CmdResult

def create_repo(path: str, default_branch: str = "main"):
    os.makedirs(path, exist_ok=True)
    exec_cmd(f"git init --initial-branch={default_branch}", cwd=path)
    exec_cmd('git config user.email "a@b.c"', cwd=path)
    exec_cmd('git config user.name "tester"', cwd=path)
    exec_cmd('git commit --allow-empty -m "Initial commit"', cwd=path)

def commit_file(repo: str, filename: str, content: str, msg: str):
    with open(os.path.join(repo, filename), "w") as f:
        f.write(content)
    exec_cmd(f"git add {filename}", cwd=repo)
    exec_cmd(f"git commit -m '{msg}'", cwd=repo)

def create_or_switch_to_branch(repo: str, branch: str):
    exec_cmd(f"git switch -c {branch} || git switch {branch}", cwd=repo)

def switch_branch(repo: str, branch: str):
    exec_cmd(f"git switch {branch}", cwd=repo)

def get_commit_hash(repo: str, branch: str) -> str:
    result: CmdResult = exec_cmd(f"git rev-parse {branch}", cwd=repo)
    return result.stdout.strip()

def get_submodule_commit_hash(repo: str, submodule_path: str) -> str:
    result: CmdResult = exec_cmd(f"git submodule status {submodule_path}", cwd=repo)
    commit_hash = result.stdout.strip().split()[0].lstrip('-+')
    return commit_hash

def repo_url(repo_path: str) -> str:
    return f"file://{repo_path}"

def add_local_submodule(repo_path: str, repo_branch: str, submodule_path: str, path_relative_to_repo: str, branch: str = "main"):
    """
    :param repo: root to repository that will track the submodule
    :type repo: str
    :param repo_branch: Branch of the main repository to which the submodule will be added (it is expected that the branch already exists and has commits)
    :type repo_branch: str
    :param submodule_path: Path to the local submodule repository
    :type submodule_path: str
    :param path_relative_to_repo: Path where the submodule will be added
    :type path_relative_to_repo: str
    :param branch: Branch of the submodule to checkout (it is expected that the branch already exists and has commits)
    :type branch: str
    """
    switch_branch(repo_path, repo_branch)
    # add the submodule (default branch will be checked out)
    cmd = f"git submodule add {repo_url(submodule_path)} {path_relative_to_repo}"
    exec_cmd(cmd, cwd=repo_path)
    submodule_dir_in_repo = os.path.join(repo_path, path_relative_to_repo)
    # switch to exact commit hash and stage the change
    switch_branch(submodule_dir_in_repo, branch)
    exec_cmd("git add .", cwd=repo_path)
    # commit the addition of the submodule at the desired branch/commit
    exec_cmd(f"git commit -m 'Add local submodule {path_relative_to_repo} branch: {branch}'", cwd=repo_path)
