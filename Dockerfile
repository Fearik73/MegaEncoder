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
RUN cd /tmp && python -c "import ocr_model; ocr_model.build()" || echo "OCR model preload skipped"

COPY . .

EXPOSE 7860

CMD ["python", "-m", "Encoder"]
