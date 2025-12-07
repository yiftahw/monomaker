import os
import json
from dataclasses import dataclass
from dataclasses_json import dataclass_json
import atexit

# TODO: maybe add a step that downloads git-filter-repo if not present from raw.githubusercontent.com
GIT_FILTER_REPO = os.path.join(os.path.expanduser("~"), "git-filter-repo")
THIS_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DIR = os.path.join(THIS_SCRIPT_DIR, "sandbox")

# register a cleanup handler to remove the sandbox on exit
atexit.register(lambda: os.system(f"rm -rf {SANDBOX_DIR}"))
    
def exec_cmd(cmd: str):
    print(f"Executing: {cmd}")
    ret = os.system(cmd)
    if ret != 0:
        raise Exception(f"Command failed: {cmd}")
    return ret
    
def create_empty_repo(path: str):
    if not os.path.exists(path):
        os.makedirs(path)
    os.chdir(path)
    return exec_cmd("git init")

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

@dataclass_json
@dataclass
class RepoConfig:
    path: str
    url: str
    branch: str

@dataclass_json
@dataclass
class Config:
    monorepo_name: str
    repositories: list[RepoConfig]

with open("config.json", "r") as f:
    config: Config = Config.from_json(f.read())

if config is None or len(config.repositories) == 0:
    raise Exception("Failed to load config or no repositories defined")

# create the monorepo directory
# TODO: different strategy to start the monorepo?
repo_path = os.path.join(THIS_SCRIPT_DIR, config.monorepo_name)

create_empty_repo(repo_path)

# merge all repos with git-filter-repo
for index, repo in enumerate(config.repositories):
    import_repo_branch(repo_path, repo.url, repo.branch, repo.path)

