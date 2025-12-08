import subprocess
from dataclasses import dataclass

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
    return CmdResult(proc.returncode, proc.stdout, proc.stderr)