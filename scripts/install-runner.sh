#!/bin/bash
set -e

RUNNER_VERSION="2.317.0"
RUNNER_DIR="$HOME/actions-runner"

mkdir -p "$RUNNER_DIR" && cd "$RUNNER_DIR"

curl -o actions-runner-linux-arm64.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"

tar xzf actions-runner-linux-arm64.tar.gz

rm actions-runner-linux-arm64.tar.gz

echo "Runner downloaded. Now run:"
echo "./config.sh --url https://github.com/godie007/codla --token YOUR_TOKEN"
echo "./svc.sh install"
echo "./svc.sh start"