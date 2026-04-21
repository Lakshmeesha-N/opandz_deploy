(venv) PS C:\Users\laksh\Desktop\opandz_deploy> python --version                                                      
Python 3.11.8 # ─────────────────────────────────────────────
# Base Image
# ─────────────────────────────────────────────
FROM python:3.11-slim

# ─────────────────────────────────────────────
# System Dependencies for WeasyPrint
# ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────
# Working Directory
# ─────────────────────────────────────────────
WORKDIR /app

# ─────────────────────────────────────────────
# Copy Requirements First (for caching)
# ─────────────────────────────────────────────
COPY requirements.txt .

RUN pip install --upgrade pip && pip install -r requirements.txt

# ─────────────────────────────────────────────
# Copy Project Files
# ─────────────────────────────────────────────
COPY . .

# ─────────────────────────────────────────────
# Expose Port
# ─────────────────────────────────────────────
EXPOSE 8000

# ─────────────────────────────────────────────
# Run FastAPI with Uvicorn
# ─────────────────────────────────────────────
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]