# On-demand LoRA trainer (CPU). NOT part of the Mesh image: build it only where fine-tuning is used.
#   docker build -t vyomi-trainer:lora1 trainer/
# core/training_core runs it through the same Docker seam as the local LLM:
#   docker run --rm --memory 12g -v <workdir>:/work -v vyomi-trainer-hf:/root/.cache/huggingface vyomi-trainer:lora1 python /opt/trainer/lora_train.py ...
# The base model is downloaded into the vyomi-trainer-hf volume on first use (SmolLM2-135M 270 MB ... Qwen2.5-3B ~6 GB).
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/trainer
COPY requirements.txt fetch_llamacpp.sh ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==$(grep ^torch== requirements.txt | cut -d= -f3)" \
 && pip install --no-cache-dir -r requirements.txt \
 && ./fetch_llamacpp.sh /opt/llama.cpp
COPY lora_train.py sample_data.py ./
ENV HF_HOME=/root/.cache/huggingface OMP_NUM_THREADS=4
