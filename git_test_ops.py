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

def add_submodule(repo: str, submodule_url: str, path_relative_to_repo: str):
    """
    Docstring for add_submodule
    
    :param repo: root to repository that will track the submodule
    :type repo: str
    :param submodule_url: URL of the submodule repository
    :type submodule_url: str
    :param path_relative_to_repo: Path where the submodule will be added
    :type path_relative_to_repo: str
    """
    exec_cmd(f"git submodule add {submodule_url} {path_relative_to_repo}", cwd=repo)
    exec_cmd("git commit -m 'Add submodule'", cwd=repo)

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
    cmd = f"git submodule add file://{submodule_path} {path_relative_to_repo}"
    exec_cmd(cmd, cwd=repo_path)
    submodule_path = os.path.join(repo_path, path_relative_to_repo)
    switch_branch(submodule_path, branch)
    exec_cmd(f"git commit -m 'Add local submodule {path_relative_to_repo} branch: {branch}'", cwd=repo_path)
