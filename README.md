# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/yiftahw/monomaker/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                   |    Stmts |     Miss |   Cover |   Missing |
|----------------------- | -------: | -------: | ------: | --------: |
| git\_test\_ops.py      |       34 |        2 |     94% |     46-47 |
| merger.py              |      272 |       61 |     78% |22, 35, 37, 58, 73, 76, 92, 95, 98, 158-159, 161-162, 164-165, 173-174, 217, 224, 248-256, 263, 301, 363-406, 410-425, 428 |
| models/\_\_init\_\_.py |        3 |        0 |    100% |           |
| models/config.py       |        9 |        0 |    100% |           |
| models/report.py       |        8 |        0 |    100% |           |
| models/repository.py   |       17 |        0 |    100% |           |
| tests.py               |      161 |        8 |     95% |20-21, 146-148, 152-153, 165 |
| utils.py               |       37 |       17 |     54% |20-21, 23-26, 31-42, 48-49 |
|              **TOTAL** |  **541** |   **88** | **84%** |           |


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