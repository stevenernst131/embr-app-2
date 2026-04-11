#!/bin/bash
# Activate the Oryx-built virtual environment
export PATH="/output/pythonenv3.12/bin:$PATH"
export VIRTUAL_ENV="/output/pythonenv3.12"
cd /output

# Start the app
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
