# AI CARE Assistant: one image for the API, the worker and the Streamlit pages.
#   * a known Python version, the same as the project's .venv (no "latest")
#   * ffmpeg, which Whisper needs to read recordings and videos
#   * the packages from requirements.txt, then the code
# docker-compose.yml starts three containers from this image, each with its own command:
#   api     uvicorn main:app
#   worker  python worker.py
#   ui      streamlit run streamlit_app.py

FROM python:3.11.16-slim

LABEL maintainer="AI CARE Assistant"
LABEL purpose="API, background worker and Streamlit pages"

ENV LANG=C.UTF-8
ENV TZ=UTC
# Show log lines at once, and do not write .pyc files into the image.
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ffmpeg turns recordings and videos into sound Whisper can read; curl is for the healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The packages first, so a change to the code does not install them all again.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501

# The API, unless docker-compose.yml gives another command.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
