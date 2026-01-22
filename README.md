# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Cover |   Missing |
|---------------------------- | -------: | -------: | ------: | --------: |
| git\_test\_ops.py           |       33 |        2 |     94% |     31-32 |
| merger.py                   |      374 |      104 |     72% |28, 41, 43, 64, 76, 81, 84, 100, 103, 106, 152-159, 208, 288, 298-299, 305, 338, 376-378, 386, 391, 423-433, 437-466, 498-509, 513-518, 532, 538-539, 557, 560-562, 565-566, 570-620, 623 |
| models/migration\_report.py |      139 |       31 |     78% |25-26, 33, 53-60, 64-65, 67-68, 70-71, 77-78, 98-101, 105-106, 108-109, 112-113, 187, 202-203 |
| models/repository.py        |       17 |        0 |    100% |           |
| tests.py                    |      166 |        1 |     99% |       203 |
| utils.py                    |       38 |        9 |     76% |20-21, 23-27, 35, 39 |
| **TOTAL**                   |  **767** |  **147** | **81%** |           |


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