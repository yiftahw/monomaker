# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Cover |   Missing |
|---------------------------- | -------: | -------: | ------: | --------: |
| git\_test\_ops.py           |       30 |        0 |    100% |           |
| merger.py                   |      363 |      104 |     71% |26, 39, 41, 62, 74, 79, 82, 98, 101, 104, 134-141, 191, 271, 281-282, 288, 316, 354-356, 364, 369, 403-413, 417-446, 480-491, 495-500, 514, 520-521, 537, 540-542, 545-546, 550-600, 603 |
| models/migration\_report.py |      135 |       31 |     77% |23-24, 30, 50-57, 61-62, 64-65, 67-68, 74-75, 95-98, 102-103, 105-106, 109-110, 170, 182-183 |
| models/repository.py        |       17 |        0 |    100% |           |
| tests.py                    |      160 |        1 |     99% |       203 |
| utils.py                    |       38 |        9 |     76% |20-21, 23-27, 35, 39 |
| **TOTAL**                   |  **743** |  **145** | **80%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/yiftahw/monomaker/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/yiftahw/monomaker/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fyiftahw%2Fmonomaker%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.