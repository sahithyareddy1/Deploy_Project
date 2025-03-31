#!/usr/bin/env bash
set -o errexit

# Install system dependencies
apt-get update && apt-get install -y cmake build-essential

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt