from typing import List
from dataclasses import dataclass
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class FileContent:
    filename: str
    content: str
    commit_msg: str


@dataclass_json
@dataclass
class BranchContent:
    name: str
    files: List[FileContent]


@dataclass_json
@dataclass
class RepoContent:
    default_branch: str
    branches: List[BranchContent]

@dataclass_json
@dataclass
class SubmoduleDef:
    """
    `path`: relative to the repo root  
    `url`: URL of the submodule
    """
    path: str
    url: str
    commit_hash: str

    def __eq__(self, other):
        """Two SubmoduleDefs are equal if they have the same path and url (commit_hash may differ across branches)."""
        if not isinstance(other, SubmoduleDef):
            return False
        return self.path == other.path and self.url == other.url

    def __hash__(self):
        """allow to be used in sets/dicts - must be consistent with __eq__"""
        return hash((self.path, self.url))