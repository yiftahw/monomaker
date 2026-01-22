import os
import copy

from typing import List, Mapping, Optional, NewType
from dataclasses import dataclass, astuple, asdict

from .repository import SubmoduleDef


# SubmoduleImportInfoEntry, SubmoduleImportInfo, MigrationImportInfo
# represent data accumulated during migration for reporting purposes.

@dataclass
class SubmoduleImportInfoEntry:
    """Represents which submodule branch applied to which metarepo branch."""
    monorepo_branch: str  # branch name in the new monorepo
    metarepo_branch: str  # what branch was used to import the metarepo files
    metarepo_commit_hash: str # commit hash of the metarepo branch that was imported
    submodule_branch: str # what branch was used to import the submodule files
    submodule_commit_hash: str # commit hash of the submodule branch that was imported
    submodule_nested_submodules: List[SubmoduleDef] # nested submodules in this submodule branch
    
    def __eq__(self, other):
        if not isinstance(other, SubmoduleImportInfoEntry):
            print("Other is not SubmoduleImportInfoEntry")
            return False
        return (self.monorepo_branch == other.monorepo_branch and
                self.metarepo_branch == other.metarepo_branch and
                self.submodule_commit_hash == other.submodule_commit_hash and
                sorted(self.submodule_nested_submodules) == sorted(other.submodule_nested_submodules))
    
    def __str__(self):
        return f"SubmoduleImportInfoEntry(monorepo_branch={self.monorepo_branch}, metarepo_branch={self.metarepo_branch}, submodule_branch={self.submodule_branch}, submodule_commit_hash={self.submodule_commit_hash}, nested_submodules={self.submodule_nested_submodules})"
    
    def __lt__(self, other):
        return astuple(self) < astuple(other)


class SubmoduleImportInfo:
    submodule_relative_path: str
    submodule_default_branch: str
    entries: List[SubmoduleImportInfoEntry]
    
    def __init__(self, submodule_relative_path: str, submodule_default_branch: str):
        self.submodule_relative_path = submodule_relative_path
        self.submodule_default_branch = submodule_default_branch
        self.entries = []
    
    def add_entry(self, monorepo_branch: str, metarepo_branch: str, metarepo_commit_hash: str, submodule_branch: str, submodule_commit_hash: str, nested_submodules: Optional[List[SubmoduleDef]] = None):
        self.entries.append(SubmoduleImportInfoEntry(monorepo_branch, metarepo_branch, metarepo_commit_hash, submodule_branch, submodule_commit_hash, nested_submodules or []))
    
    def __str__(self):
        s = f"Submodule Import Info for {self.submodule_relative_path}:\n"

        for entry in self.entries:
            s += f"  - {entry.monorepo_branch}: metarepo branch: {entry.metarepo_branch} (commit: {entry.metarepo_commit_hash}), submodule branch: {entry.submodule_branch} (commit: {entry.submodule_commit_hash})\n"
            s += f"    - nested submodules:\n" if len(entry.submodule_nested_submodules) > 0 else ""
            for nested in entry.submodule_nested_submodules:
                s += f"    path: {nested.path}, url: {nested.url}, commit: {nested.commit_hash}\n"
        return s
    
    def __eq__(self, other):
        if not isinstance(other, SubmoduleImportInfo):
            print("Other is not SubmoduleImportInfo")
            return False
        if self.submodule_relative_path != other.submodule_relative_path:
            print(f"Submodule paths differ: {self.submodule_relative_path} != {other.submodule_relative_path}")
            return False
        if len(self.entries) != len(other.entries):
            print(f"Number of entries differ: {len(self.entries)} != {len(other.entries)}")
            return False
        # sort each list prior to comparison
        self.entries.sort()
        other.entries.sort()
        for e1, e2 in zip(self.entries, other.entries):
            if e1 != e2:
                print(f"Entries differ:\n{e1}\n{e2}")
                return False
        return True


class MigrationImportInfo:
    submodules_info: Mapping[str, SubmoduleImportInfo]
    metarepo_default_branch: str
    metarepo_name: str
    monorepo_name: str
    
    def __init__(self, metarepo_default_branch: str, metarepo_name: str = "metarepo", monorepo_name: str = "monorepo"):
        self.submodules_info = dict()
        self.metarepo_default_branch = metarepo_default_branch
        self.metarepo_name = metarepo_name
        self.monorepo_name = monorepo_name
    
    def add_submodule_entry(self, submodule_relative_path: str, info: SubmoduleImportInfo):
        self.submodules_info[submodule_relative_path] = info
    
    def __str__(self):
        s = "Migration Report:\n"
        for _, info in self.submodules_info.items():
            s += str(info) + "\n"
        return s
    
    def __eq__(self, other):
        if not isinstance(other, MigrationImportInfo):
            print("Other is not MigrationImportInfo")
            return False
        if set(self.submodules_info.keys()) != set(other.submodules_info.keys()):
            print(f"Submodule keys differ: {set(self.submodules_info.keys())} != {set(other.submodules_info.keys())}")
            return False
        for key in self.submodules_info.keys():
            if self.submodules_info[key] != other.submodules_info[key]:
                print(f"Submodule info for {key} differs")
                return False
        return True

RelativePath = NewType('RelativePath', str)
BranchName = NewType('BranchName', str)

@dataclass
class SubmoduleTrackingInfo:
    url: str
    commit_hash: str

    def as_dict(self):
        return asdict(self)

@dataclass
class ImportedSubmoduleInfo:
    branch: str
    commit_hash: str

    def as_dict(self):
        return asdict(self)

@dataclass
class MigrationReportEntry:
    """
    Represents the migration report in a structured format, 
    representing the views needed for creating the monorepo.
    Intended for human-readable reporting purposes.
    """
    metarepo_branch: str
    metarepo_commit_hash: str
    imported_submodules: Mapping[RelativePath, ImportedSubmoduleInfo]
    tracked_nested_submodules: Mapping[RelativePath, SubmoduleTrackingInfo]

    def as_dict(self):
        return {
            "metarepo_branch": self.metarepo_branch,
            "metarepo_commit_hash": self.metarepo_commit_hash,
            "imported_submodules": {k: v.as_dict() for k, v in self.imported_submodules.items()},
            "tracked_nested_submodules": {k: v.as_dict() for k, v in self.tracked_nested_submodules.items()}
        }

class MigrationReport:
    monorepo_branches: Mapping[BranchName, MigrationReportEntry] = dict()
    metarepo_name: str
    monorepo_name: str

    # TODO: reduce code duplication with register_submodule_from_metarepo_branch 
    def register_submodule_import(self, monorepo_branch: str, metarepo_branch: str, metarepo_commit_hash: str, submodule_relative_path: str, submodule_branch: str, submodule_commit_hash: str, nested_submodules: List[SubmoduleDef]):
        if not monorepo_branch in self.monorepo_branches:
            self.monorepo_branches[monorepo_branch] = MigrationReportEntry(
                metarepo_branch=metarepo_branch,
                metarepo_commit_hash=metarepo_commit_hash,
                imported_submodules=dict(),
                tracked_nested_submodules=dict()
            )
        
        # add the imported submodule
        self.monorepo_branches[monorepo_branch].imported_submodules[submodule_relative_path] = ImportedSubmoduleInfo(
            branch=submodule_branch,
            commit_hash=submodule_commit_hash
        )

        # add the tracked nested submodules
        for nested in nested_submodules:
            nested_relative_path = os.path.join(submodule_relative_path, nested.path)
            self.monorepo_branches[monorepo_branch].tracked_nested_submodules[nested_relative_path] = SubmoduleTrackingInfo(
                url=nested.url,
                commit_hash=nested.commit_hash
            )

    def register_submodule_from_metarepo_branch(self, monorepo_branch: str, metarepo_branch: str, metarepo_commit_hash: str, submodule_relative_path: str, submodule_branch: str, submodule_commit_hash: str, nested_submodules: List[SubmoduleDef]):
        # `metarepo_branch` here is used as the base of the submodule import
        if metarepo_branch not in self.monorepo_branches:
            raise ValueError(f"Monorepo branch {metarepo_branch} not registered yet in report.")
        
        # create the monorepo branch entry only if was not created by a previous submodule import.
        # i.e. there might be multiple submodules with the same "feature" branch, and "feautre" does not exist in the metarepo.
        if monorepo_branch not in self.monorepo_branches:
            self.monorepo_branches[monorepo_branch] = copy.deepcopy(self.monorepo_branches[metarepo_branch])

        # add the imported submodule
        self.monorepo_branches[monorepo_branch].imported_submodules[submodule_relative_path] = ImportedSubmoduleInfo(
            branch=submodule_branch,
            commit_hash=submodule_commit_hash
        )

        # add the tracked nested submodules
        for nested in nested_submodules:
            nested_relative_path = os.path.join(submodule_relative_path, nested.path)
            self.monorepo_branches[monorepo_branch].tracked_nested_submodules[nested_relative_path] = SubmoduleTrackingInfo(
                url=nested.url,
                commit_hash=nested.commit_hash
            )


    def __init__(self, report_info: MigrationImportInfo):
        self.entries = []
        self.metarepo_name = report_info.metarepo_name
        self.monorepo_name = report_info.monorepo_name
        metarepo_default_branch = report_info.metarepo_default_branch
        
        # need to first populate the metarepo default branch,
        # as it's report might serve as the base for other branches
        for submodule_relative_path, submodule_info in report_info.submodules_info.items():
            for entry in submodule_info.entries:
                is_metarepo_default_branch = entry.metarepo_branch == metarepo_default_branch
                is_submodule_branch_same_or_default = entry.submodule_branch in [metarepo_default_branch, submodule_info.submodule_default_branch]
                if is_metarepo_default_branch and is_submodule_branch_same_or_default:
                    self.register_submodule_import(entry.monorepo_branch, entry.metarepo_branch, entry.metarepo_commit_hash, submodule_relative_path, entry.submodule_branch, entry.submodule_commit_hash, entry.submodule_nested_submodules)

        # now populate all other branches
        for submodule_relative_path, submodule_info in report_info.submodules_info.items():
            for entry in submodule_info.entries:
                    # need to decide if this submodule feature branch needs to be registered from the metarepo default branch
                    is_metarepo_default_branch = entry.metarepo_branch == metarepo_default_branch
                    is_submodule_branch_same_or_default = entry.submodule_branch in [metarepo_default_branch, submodule_info.submodule_default_branch]
                    if is_metarepo_default_branch:
                        if is_submodule_branch_same_or_default:
                            # already registered in the first pass
                            continue
                        else:
                            self.register_submodule_from_metarepo_branch(entry.monorepo_branch, metarepo_default_branch, entry.metarepo_commit_hash, submodule_relative_path, entry.submodule_branch, entry.submodule_commit_hash, entry.submodule_nested_submodules)
                    else:
                        self.register_submodule_import(entry.monorepo_branch, entry.metarepo_branch, entry.metarepo_commit_hash, submodule_relative_path, entry.submodule_branch, entry.submodule_commit_hash, entry.submodule_nested_submodules)
                
    def __str__(self):
        s = "Migration Report:\n"
        for monorepo_branch, entry in self.monorepo_branches.items():
            s += f"\n{self.monorepo_name} branch: {monorepo_branch}\n"
            s += f"  Imported branches:\n"
            s += f"  - {self.metarepo_name}: branch={entry.metarepo_branch}, commit={entry.metarepo_commit_hash}\n"
            for submodule_path, submodule_info in entry.imported_submodules.items():
                s += f"  - {submodule_path}: branch={submodule_info.branch}, commit={submodule_info.commit_hash}\n"
            s += f"  Tracked git submodules:\n" if len(entry.tracked_nested_submodules) > 0 else ""
            for nested_path, tracking_info in entry.tracked_nested_submodules.items():
                s += f"  - {nested_path}: url={tracking_info.url}, commit={tracking_info.commit_hash}\n"
        return s
    
    def as_dict(self):
        return {
            "monorepo_branches": {branch: entry.as_dict() for branch, entry in self.monorepo_branches.items()},
            "metarepo_name": self.metarepo_name,
            "monorepo_name": self.monorepo_name
        }


