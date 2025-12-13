# monomaker

Migrate from a meta repo to a monorepo with ease  

[![Coverage badge](https://raw.githubusercontent.com/yiftahw/monomaker/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)  

## Warning
  
This project is aimed at a very specific submodule-based workflow and is not trying to be general-purpose.  
If you have never ignored a submodule SHA change on purpose, this repository is probably not relevant to you.

## What This Does

This tool migrates a codebase from a **meta-repository with submodules** into a **monorepo**, assuming that submodule pointers in the meta-repo are not kept up to date.

Feature branches might exist partially in some submodules or the metarepo itself, while others remain on the default branch. The migrated monorepo feature branch should reflect this workflow.

## How Branches Are Resolved

First, a set of all feature branches across the meta-repo and its first-layer submodules is calculated.  
For each branch in this set, a corresponding monorepo branch is created: each repository contributes the feature branch if it exists, or falls back to its default branch if it does not.

Only **first-layer submodules** are imported in this process.  
Second-layer (nested) submodules are retained in the monorepo at their original relative paths and commit hashes, preserving their history without flattening.
