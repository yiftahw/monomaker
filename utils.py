import subprocess
from dataclasses import dataclass
import json
import os

@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str

def exec_cmd(cmd: str, cwd: str = None, verbose: bool = True, verbose_output: bool = False) -> CmdResult:
    """
    Execute a shell command and return the result.
    """
    if verbose:
        print(f"Executing command: {cmd} (cwd={cwd or '.'})")
    proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if verbose_output:
        print(f"Command stdout: {proc.stdout}")
        print(f"Command stderr: {proc.stderr}")
    if proc.returncode != 0:
        print(f"Command '{cmd}' failed with return code {proc.returncode}")
        if proc.stderr:
            print(f"Error output: {proc.stderr}")            
        raise RuntimeError(f"Command '{cmd}' failed with return code {proc.returncode}\n{proc.stderr}\n{proc.stdout}")
    return CmdResult(proc.returncode, proc.stdout, proc.stderr)


def listdir_list(path):
    tree = []
    for entry in os.listdir(path):
        if entry.startswith('.git'):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            # For directories, include a tuple: (name, nested_list)
            tree.append([entry, listdir_list(full)])
        else:
            # For files, just include the name
            tree.append(entry)
    return tree

def pretty_print_list(nested_list, indent=4):
    """
    Returns a pretty-printed string of a nested list.
    """
    nested_as_json = json.dumps(nested_list, indent=indent)
    return nested_as_json

def header_string(msg: str) -> str:
    msg = "=== " + msg + " ==="
    msg_len = len(msg)
    border = "=" * msg_len
    return f"{border}\n{msg}\n{border}"
