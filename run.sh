#!/bin/bash


BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd ${BASE_DIR}/src

env_python=$(pipenv --venv)/bin/python
$env_python server.py
