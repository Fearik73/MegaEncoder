#!/bin/bash
set -e
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

$SUDO apt-get update
$SUDO apt-get install -y ffmpeg aria2 megatools python3-pip build-essential

pip3 install -r requirements.txt

pip3 install --no-deps rapidocr-onnxruntime==1.4.4
pip3 install --no-deps "rapidocr>=3.10.0"

(
  cd Encoder/utils/ocr
  python3 - <<'PYEOF'
import logging
import numpy as np
import ocr_model

logging.basicConfig(level=logging.INFO)
engine, kind = ocr_model.build()
engine(np.full((48, 320, 3), 255, np.uint8))
print("OCR preload ok:", kind)
PYEOF
) || echo "OCR model preload skipped, models will download on first start"

echo "Done. Start the bot with:  python3 -m Encoder"
