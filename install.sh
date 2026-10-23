#!/bin/bash
set -e
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

$SUDO apt-get update
$SUDO apt-get install -y ffmpeg aria2 megatools python3-pip

pip3 install -r requirements.txt

echo "Done. Start the bot with:  python3 -m Encoder"
