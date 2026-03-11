#!/bin/bash
set -e

cd /app/
plantform="$(uname -m)"
PLANT_PATH=${PLANT_PATH:-/app/env}
plant="${PLANT_PATH}_${plantform}"
source /app/environment.sh
source "$plant/bin/activate"
python3 main.py -job True -init True
