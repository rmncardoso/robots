#!/usr/bin/env bash
# Ship the local strands-robots tree to the provisioned instance and run
# smoke.py inside the pinned Isaac Sim container. Everything moves over SSM +
# a presigned S3 URL, so the instance needs no S3 permissions and no ingress.
set -euo pipefail

STATE_FILE="$(dirname "$0")/.instance.json"
[ -f "$STATE_FILE" ] || { echo "no .instance.json - run ./provision.sh first"; exit 1; }
IID=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['instance_id'])")
REGION=$(python3 -c "import json;print(json.load(open('$STATE_FILE'))['region'])")
REPO_ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="strands-isaac-example-$ACCOUNT-$REGION"

echo "== packing the local tree ($REPO_ROOT) =="
TARBALL=$(mktemp -t strands-robots-XXXX).tgz
tar czf "$TARBALL" -C "$REPO_ROOT" \
  --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  strands_robots examples pyproject.toml README.md

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws s3 mb "s3://$BUCKET" --region "$REGION" >/dev/null
aws s3 cp "$TARBALL" "s3://$BUCKET/payload.tgz" --region "$REGION" >/dev/null
URL=$(aws s3 presign "s3://$BUCKET/payload.tgz" --region "$REGION" --expires-in 3600)
rm -f "$TARBALL"

echo "== staging on the instance =="
STAGE=$(cat <<EOF
set -e
rm -rf /opt/strands && mkdir -p /opt/strands
curl -sS -o /tmp/payload.tgz "$URL"
tar xzf /tmp/payload.tgz -C /opt/strands
cat > /opt/strands/inner.sh <<'INNER'
#!/bin/bash
# The strands-agents requirement is READ OUT OF the packed pyproject.toml rather
# than written here. A bound copied into this script goes stale silently: it
# would install a version the package itself refuses, and pip would exit 0, so
# the smoke run's first failure would be an import error with no hint that the
# example asked for the wrong version. (It did - this line carried >=1.7.0
# against a declared floor of >=1.13.0, and tests/test_dependency_audit.py is
# what caught it.)
# The \$ are escaped because this text is built inside an UNQUOTED outer heredoc
# (<<EOF, which must expand \$URL above), so an unescaped \$( ) would be evaluated
# by the SHELL BUILDING THE SCRIPT rather than by the container running it - which
# is what happened: the host has no /isaac-sim/python.sh, so it failed with
# "No such file or directory" and then "REQ: unbound variable" under set -u.
REQ=\$(/isaac-sim/python.sh -c "import re, pathlib; print(re.search(r'\"(strands-agents>=[^\"]*)\"', pathlib.Path('/sr/pyproject.toml').read_text()).group(1))")
echo "installing \$REQ (from pyproject)"
/isaac-sim/python.sh -m pip -q install "\$REQ" opencv-python-headless 2>&1 | tail -1
PYTHONPATH=/sr /isaac-sim/python.sh /sr/examples/isaac_on_aws/smoke.py
INNER
chmod +x /opt/strands/inner.sh
rm -f /opt/strands/smoke.log
nohup docker run --rm --gpus all -e OMNI_KIT_ACCEPT_EULA=YES -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
  -v /opt/strands:/sr --entrypoint bash nvcr.io/nvidia/isaac-sim:6.0.1 /sr/inner.sh \
  > /opt/strands/smoke.log 2>&1 &
echo launched
EOF
)
python3 - "$STAGE" <<'PY' > /tmp/strands_ssm_params.json
import json, sys
print(json.dumps({"commands": sys.argv[1].splitlines()}))
PY
CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
  --document-name AWS-RunShellScript --parameters file:///tmp/strands_ssm_params.json \
  --query 'Command.CommandId' --output text)
sleep 20
aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" \
  --query 'Status' --output text

echo "== waiting for the smoke run (Kit boot + scene; typically 5-8 minutes) =="
for i in $(seq 1 60); do
  sleep 15
  CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
    --document-name AWS-RunShellScript \
    --parameters 'commands=["grep -c \"SMOKE SUMMARY\" /opt/strands/smoke.log 2>/dev/null || echo 0"]' \
    --query 'Command.CommandId' --output text)
  sleep 8
  DONE=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" \
    --query 'StandardOutputContent' --output text | tr -d '[:space:]')
  [ "$DONE" = "1" ] && break
done

echo "== result =="
CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sed -n \"/SMOKE SUMMARY/,\\$p\" /opt/strands/smoke.log"]' \
  --query 'Command.CommandId' --output text)
sleep 10
aws ssm get-command-invocation --region "$REGION" --command-id "$CID" --instance-id "$IID" \
  --query 'StandardOutputContent' --output text
