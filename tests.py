import unittest
import tempfile
import shutil
import os
from pprint import pprint
import git_test_ops
from models.repository import FileContent, BranchContent, RepoContent

import merger

def create_temporary_repo(content: RepoContent) -> str:
    """Creates a temporary repository and returns its path."""
    tempdir = tempfile.mkdtemp()
    git_test_ops.create_repo(tempdir)
    for branch in content.branches:
        git_test_ops.create_branch(tempdir, branch.name)
        for file in branch.files:
            git_test_ops.commit_file(tempdir, file.filename, file.content, file.commit_msg)
    return tempdir


def create_repo_content() -> RepoContent:
    return RepoContent(
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

    def assert_file_content(self, repo_path: str, filename: str, expected_content: str):
        file_path = os.path.join(repo_path, filename)
        self.assertTrue(os.path.isfile(file_path))
        with open(file_path, "r") as f:
            content = f.read()
        self.assertEqual(content, expected_content)

    def setUp(self):
        self.repo_content = create_repo_content()
        self.repo_path = create_temporary_repo(self.repo_content)
        self.submodule_a_content = create_submodule_content()
        self.submodule_a_path = create_temporary_repo(self.submodule_a_content)
        git_test_ops.add_local_submodule(
            self.repo_path,
            self.submodule_a_path,
            self.submodule_relative_path
        )

    def tearDown(self):
        shutil.rmtree(self.repo_path)
        shutil.rmtree(self.submodule_a_path)

    def test_repo_creation(self):
        # Verify main branch files
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(self.repo_path, branch.name)
            for file in branch.files:
                self.assert_file_content(self.repo_path, file.filename, file.content)

    def test_submodule_integration(self):
        git_test_ops.switch_branch(self.repo_path, "main")
        submodule_path = os.path.join(self.repo_path, self.submodule_relative_path)
        self.assertTrue(os.path.isdir(submodule_path))
        for branch in self.submodule_a_content.branches:
            git_test_ops.switch_branch(submodule_path, branch.name)
            for file in branch.files:
                self.assert_file_content(submodule_path, file.filename, file.content)

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
        temp_repo_path = create_temporary_repo(RepoContent(branches=[]))
        merger.import_meta_repo(temp_repo_path, self.repo_path)
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(temp_repo_path, branch.name)
            for file in branch.files:
                self.assert_file_content(temp_repo_path, file.filename, file.content)
        
if __name__ == "__main__":
    unittest.main()