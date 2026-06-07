# Start FastAPI + Streamlit in separate windows
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; Write-Host '🚀 FastAPI starting on http://localhost:8000' -ForegroundColor Cyan; uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload"

Start-Sleep -Seconds 2

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; Write-Host '🎨 Streamlit starting on http://localhost:8501' -ForegroundColor Green; streamlit run frontend/app.py --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false"

Write-Host ""
Write-Host "Both servers are starting..." -ForegroundColor Yellow
Write-Host "  FastAPI  → http://localhost:8000" -ForegroundColor Cyan
Write-Host "  API Docs → http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "  App      → http://localhost:8501" -ForegroundColor Green
Write-Host ""
Write-Host "Close the two opened windows to stop the servers." -ForegroundColor Gray
