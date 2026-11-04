FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg aria2 megatools build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps rapidocr-onnxruntime==1.4.4 "rapidocr>=3.10.0"

COPY Encoder/utils/ocr/ocr_model.py /tmp/ocr_model.py
RUN cd /tmp && python -c 'import logging, numpy as np, ocr_model; logging.basicConfig(level=logging.INFO); \
e, k = ocr_model.build(); e(np.full((48, 320, 3), 255, np.uint8)); print("OCR preload ok:", k)' \
    || echo "OCR model preload skipped"

COPY . .

EXPOSE 7860

CMD ["python", "-m", "Encoder"]
