import os
import json
import atexit
import subprocess
import argparse

from models import Config, RepoConfig, RepositoryReport, RepositoryReportEntry

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
    curr_dir = os.getcwd()
    if not os.path.exists(path):
        os.makedirs(path)
    os.chdir(path)
    ret = exec_cmd("git init")
    os.chdir(curr_dir)
    return ret

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

def get_all_branches_in_origin(url: str) -> list[str]:
    cmd = f"git ls-remote --heads {url}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Failed to get branches from {url}: {result.stderr}")
    branches = []
    for _, ref in (line.split() for line in result.stdout.splitlines()):
        # use only the branch name, i.e discard refs/heads/, and ignore HEAD
        if ref.startswith("refs/heads/"):
            branch_name = ref[len("refs/heads/"):]
            branches.append(branch_name)
    return branches

def load_config(config_file: str = "config.json") -> Config:
    """Load and validate configuration from JSON file."""
    with open(config_file, "r") as f:
        config = Config.from_json(f.read())
    
    if not config or not config.repositories:
        raise ValueError("Configuration is empty or has no repositories defined")
    
    return config

def generate_branch_report(config: Config, output_file: str = None):
    """Generate a report of all branches for each repository."""
    report = RepositoryReport(repositories=[])
    
    for repo in config.repositories:
        branches = get_all_branches_in_origin(repo.url)
        report.repositories.append(RepositoryReportEntry(url=repo.url, branches=branches))
    
    report_json = report.to_json(indent=4)
    
    if output_file:
        with open(output_file, "w") as f:
            f.write(report_json)
        print(f"Branch report generated at {output_file}")
    else:
        print(report_json)

def clone_and_validate_monorepo(monorepo_url: str, repo_path: str):
    """Clone monorepo and validate it's empty or nearly empty."""
    print(f"Cloning monorepo from {monorepo_url}...")
    
    if os.path.exists(repo_path):
        raise Exception(f"Directory {repo_path} already exists. Please remove it first.")
    
    exec_cmd(f"git clone {monorepo_url} {repo_path}")
    
    # Validate the monorepo is empty or nearly empty
    allowed_files = {'.git', 'README.md', 'README', '.gitignore', '.gitattributes'}
    actual_files = set(os.listdir(repo_path))
    unexpected_files = actual_files - allowed_files
    
    if unexpected_files:
        raise Exception(f"Monorepo is not empty. Found unexpected files: {', '.join(unexpected_files)}. "
                       f"Only README, .gitignore, and .gitattributes are allowed.")
    
    print("Monorepo validated as empty.")

def merge_repositories(config: Config):
    """Merge all repositories into a monorepo."""
    repo_path = os.path.join(THIS_SCRIPT_DIR, config.monorepo_name)
    
    # Clone or create the monorepo
    if config.monorepo_url:
        clone_and_validate_monorepo(config.monorepo_url, repo_path)
    else:
        print("No monorepo_url specified, creating empty repository...")
        create_empty_repo(repo_path)
    
    # Get all branches for each repository and merge them
    for repo in config.repositories:
        print(f"\nProcessing repository: {repo.url}")
        branches = get_all_branches_in_origin(repo.url)
        print(f"Found {len(branches)} branches: {', '.join(branches)}")
        
        for branch in branches:
            print(f"\n  Merging branch: {branch}")
            import_repo_branch(repo_path, repo.url, branch, repo.path)
    
    print(f"\nAll repositories and branches merged into {repo_path}")

def main():
    parser = argparse.ArgumentParser(description="Monorepo maker - merge multiple repositories into one")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Branch report command
    branch_parser = subparsers.add_parser("branch-report", aliases=["b"],
                                          help="Generate a report of all branches for each repository")
    branch_parser.add_argument("-o", "--output", type=str, metavar="FILE",
                              help="Output file for branch report (if not specified, prints to console)")
    
    # Merge command
    merge_parser = subparsers.add_parser("merge", aliases=["m"],
                                         help="Merge all repositories into a monorepo")
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
    except FileNotFoundError:
        print("Error: config.json not found")
        return
    except ValueError as e:
        print(f"Error: {e}")
        return
    except Exception as e:
        print(f"Error loading config.json: {e}")
        return
    
    # Execute the requested command
    if args.command in ["branch-report", "b"]:
        generate_branch_report(config, args.output)
    elif args.command in ["merge", "m"]:
        merge_repositories(config)

if __name__ == "__main__":
    main()