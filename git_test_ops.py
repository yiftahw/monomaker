"""
Simple API for Git operations.
"""
import os
from utils import exec_cmd, CmdResult

def create_repo(path: str):
    os.makedirs(path, exist_ok=True)
    exec_cmd("git init --initial-branch=main", cwd=path)
    exec_cmd('git config user.email "a@b.c"', cwd=path)
    exec_cmd('git config user.name "tester"', cwd=path)
    exec_cmd('git config protocol.file.allow always', cwd=path)

def commit_file(repo: str, filename: str, content: str, msg: str):
    with open(os.path.join(repo, filename), "w") as f:
        f.write(content)
    exec_cmd(f"git add {filename}", cwd=repo)
    exec_cmd(f"git commit -m '{msg}'", cwd=repo)

def create_branch(repo: str, branch: str):
    exec_cmd(f"git switch -c {branch}", cwd=repo)

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

def add_local_submodule(repo_path: str, submodule_path: str, path_relative_to_repo: str):
    """
    Docstring for add_local_submodule
    
    :param repo: root to repository that will track the submodule
    :type repo: str
    :param submodule_path: Path to the local submodule repository
    :type submodule_path: str
    :param path_relative_to_repo: Path where the submodule will be added
    :type path_relative_to_repo: str
    """
    cmd = f"git -c protocol.file.allow=always submodule add file://{submodule_path} {path_relative_to_repo}"
    exec_cmd(cmd, cwd=repo_path)
    exec_cmd("git commit -m 'Add local submodule'", cwd=repo_path)
