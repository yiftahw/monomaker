#!/usr/bin/env python3

import unittest
import tempfile
import shutil
import os
from pprint import pprint, PrettyPrinter
import io
import json

from utils import exec_cmd, listdir_list, pretty_print_list, header_string
import git_test_ops
from models.repository import FileContent, BranchContent, RepoContent
import merger

with open("debug.log", "w") as f:
    f.write("Debug Log\n")

def debug_log(message: str):
    with open("debug.log", "a") as f:
        f.write(message + "\n")

def create_and_fill_branch(repo_path: str, branch_content: BranchContent, branch_name: str, default_branch: str):
    """Create a branch and fill it with files as per RepoContent."""
    # switch to the default branch first, to branch off it
    git_test_ops.switch_branch(repo_path, default_branch)
    git_test_ops.create_or_switch_to_branch(repo_path, branch_name)
    # get the branch content
    for file in branch_content.files:
        git_test_ops.commit_file(repo_path, file.filename, file.content, file.commit_msg)

def create_temporary_repo(content: RepoContent) -> str:
    """Creates a temporary repository and returns its path."""
    tempdir = tempfile.mkdtemp()
    git_test_ops.create_repo(tempdir, content.default_branch)
    # start with creating the default branch first
    default_branch_content = next((b for b in content.branches if b.name == content.default_branch), None)
    if default_branch_content is not None:
        create_and_fill_branch(tempdir, default_branch_content, content.default_branch, content.default_branch)
    # create other branches
    for branch in content.branches:
        if branch.name == content.default_branch:
            continue  # already created
        create_and_fill_branch(tempdir, branch, branch.name, content.default_branch)
    git_test_ops.switch_branch(tempdir, content.default_branch)
    return tempdir


def create_repo_content() -> RepoContent:
    return RepoContent(
        default_branch="main",
        branches=[
            BranchContent(
                name="main",
                files=[
                    FileContent(
                        filename="file1.txt",
                        content="Hello, World!",
                        commit_msg="Add file1.txt"
                    ),
                    FileContent(
                        filename="file2.txt",
                        content="This is a test.",
                        commit_msg="Add file2.txt"
                    )
                ]
            ),
            BranchContent(
                name="feature",
                files=[
                    FileContent(
                        filename="feature.txt",
                        content="Feature branch file.",
                        commit_msg="Add feature.txt"
                    )
                ]
            )
        ]
    )

def create_submodule_content() -> RepoContent:
    return RepoContent(
        default_branch="main",
        branches=[
            BranchContent(
                name="main",
                files=[
                    FileContent(
                        filename="subfile.txt",
                        content="Submodule file content.",
                        commit_msg="Add subfile.txt"
                    )
                ]
            ),
            BranchContent(
                name="dev",
                files=[
                    FileContent(
                        filename="devfile.txt",
                        content="Dev branch file in submodule.",
                        commit_msg="Add devfile.txt"
                    )
                ]
            )
        ]
    )

class TestGitOps(unittest.TestCase):
    repo_content: RepoContent
    repo_path: str
    submodule_a_path: str
    submodule_a_content: RepoContent
    submodule_relative_path: str = "submodule_a"

    def verify_submodule_import(self, monorepo_path: str, submodule_path: str, 
                                expected_branches: set, submodule_content: RepoContent):
        """Verify that submodule branches and files were correctly imported into monorepo."""
        # verify all branches were imported
        monorepo_branches = set(merger.get_all_branches(monorepo_path))
        self.assertTrue(expected_branches.issubset(monorepo_branches), f"Expected branches {expected_branches} not all found in monorepo branches {monorepo_branches}")
        
        # verify files in each branch
        for branch in submodule_content.branches:
            # we switch branches in the main repo, submodule files should now exist in it
            git_test_ops.switch_branch(monorepo_path, branch.name)
            submodule_files = set([file.filename for file in branch.files])
            imported_files = set(os.listdir(os.path.join(monorepo_path, submodule_path)))
            self.assertTrue(submodule_files.issubset(imported_files))

    def check_file_content(self, repo_path: str, filename: str, expected_content: str) -> bool:
        file_path = os.path.join(repo_path, filename)
        if not os.path.isfile(file_path):
            debug_log(f"File {file_path} does not exist.")
            debug_log(f"Current directory listing: {pretty_print_list(listdir_list(repo_path))}")
            return False
        with open(file_path, "r") as f:
            content = f.read()
        if not content == expected_content:
            debug_log(f"File {file_path} content mismatch.\nExpected:\n{expected_content}\nGot:\n{content}")
            return False
        return True

    def setUp(self):
        self.repo_content = create_repo_content()
        self.repo_path = create_temporary_repo(self.repo_content)
        self.submodule_a_content = create_submodule_content()
        self.submodule_a_path = create_temporary_repo(self.submodule_a_content)
        self.monorepo_path = create_temporary_repo(RepoContent(default_branch="main", branches=[]))
        git_test_ops.add_local_submodule(
            self.repo_path,
            self.submodule_a_path,
            self.submodule_relative_path
        )
        print(header_string("Setup complete"))

    def tearDown(self):
        shutil.rmtree(self.monorepo_path)
        shutil.rmtree(self.repo_path)
        shutil.rmtree(self.submodule_a_path)

    def test_repo_creation(self):
        # Verify main branch files
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(self.repo_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(self.repo_path, file.filename, file.content))

    def test_submodule_integration(self):
        git_test_ops.switch_branch(self.repo_path, "main")
        submodule_path = os.path.join(self.repo_path, self.submodule_relative_path)
        self.assertTrue(os.path.isdir(submodule_path))
        for branch in self.submodule_a_content.branches:
            git_test_ops.switch_branch(submodule_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(submodule_path, file.filename, file.content))

    def test_merger_get_all_branches(self):
        branches = set(merger.get_all_branches(self.repo_path))
        expected_branches = set([branch.name for branch in self.repo_content.branches])
        self.assertCountEqual(branches, expected_branches)

        submodule_branches = set(merger.get_all_branches(self.submodule_a_path))
        expected_submodule_branches = set([branch.name for branch in self.submodule_a_content.branches])
        self.assertCountEqual(submodule_branches, expected_submodule_branches)

    def test_merger_get_all_submodules(self):
        submodules = merger.get_all_submodules(self.repo_path)
        self.assertEqual(len(submodules), 1)
        self.assertEqual(submodules[0].path, self.submodule_relative_path)

    def test_merger_import_meta_repo(self):
        merger.import_meta_repo(self.monorepo_path, self.repo_path)
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(self.monorepo_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(self.monorepo_path, file.filename, file.content))

    def test_merger_import_submodule(self):
        # first thing we do after clone is to get the HEAD, it will be consider the default
        default_branch = merger.get_head_branch(self.repo_path)
        self.assertTrue(default_branch == "main")
        metarepo_tracked_submodules_mapping = merger.get_metarepo_tracked_submodules_mapping(self.repo_path)
        # import the main repo first
        merger.import_meta_repo(self.monorepo_path, self.repo_path)
        # import all submodules
        submodules = metarepo_tracked_submodules_mapping.keys()
        submodule_names = [submodule.path for submodule in submodules]
        self.assertEqual(submodule_names, ["submodule_a"])
        print(header_string(f"Found submodules to import: {submodule_names}"))
        for submodule in submodules:
            print(header_string(f"Importing submodule {submodule.path}"))
            submodule_path_in_metarepo = os.path.join(self.repo_path, submodule.path)
            # need to have local copies of all branches to be able to clone (copy) them locally (without network)
            # this is because we modify (in a destructive way) the .git content when running git-filter-repo
            merger.update_all_repo_branches(submodule_path_in_metarepo)
            expected_submodule_branches = set(merger.get_all_branches(submodule_path_in_metarepo))
            print(header_string(f"Expected submodule {submodule.path} branches: {expected_submodule_branches}"))
            # import the submodule (clones it locally per branch, modifies it, and merges into the monorepo)
            merger.import_submodule(self.monorepo_path, 
                submodule.url, 
                submodule.path, 
                default_branch, 
                set(merger.get_all_branches(self.repo_path)), 
                expected_submodule_branches, 
                metarepo_tracked_submodules_mapping[submodule])
            
            # verify the import was successful
            self.verify_submodule_import(self.monorepo_path, submodule.path, 
                                        expected_submodule_branches, self.submodule_a_content)

if __name__ == "__main__":
    unittest.main()
