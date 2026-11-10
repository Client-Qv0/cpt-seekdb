#!/bin/sh
set -eu
cd /home/li/minivectordb-exact-scan-20261110
export PYTHONDONTWRITEBYTECODE=1
p=validation/exact-scan-li-20261110
docker image inspect mvdb-li-exact:c2-3490b49 > "$p/runtime-image.json"
python3 "$p/resource_driver.py" --binary /home/li/minivectordb-exact-scan-20261110/build-exact-c2/minivectordb --expected-binary-sha256 b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67 --source-root /home/li/minivectordb-exact-scan-20261110 --source-manifest "$p/candidate-production-manifest.json" --output "$p/resource-final" > "$p/resource-final.log" 2>&1
echo 0 > "$p/resource-final.exit"
