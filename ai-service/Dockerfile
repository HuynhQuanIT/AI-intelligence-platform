FROM python:3.11-slim
WORKDIR /app
# OCR cho ảnh và PDF scan. Bỏ qua để image nhẹ hơn: docker compose build --build-arg INSTALL_OCR=false
ARG INSTALL_OCR=true
RUN if [ "$INSTALL_OCR" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng \
      && rm -rf /var/lib/apt/lists/*; \
    fi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Bộ đo chất lượng RAG: dùng bởi trang "RAG Evaluation" của admin và lệnh python -m eval.run_rag_eval.
COPY eval ./eval
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
