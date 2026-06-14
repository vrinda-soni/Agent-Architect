# Start FastAPI backend + Chainlit frontend
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\vrind\AppData\Local\Programs\Python\Python312\python.exe"

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
  "cd '$root'; `$env:PYTHONPATH='$root'; Write-Host '🚀 FastAPI on http://localhost:8000' -ForegroundColor Cyan; & '$python' -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload"

Start-Sleep -Seconds 2

Start-Process powershell -ArgumentList "-NoExit", "-Command", `
  "cd '$root'; `$env:PYTHONPATH='$root'; Write-Host '⚡ Chainlit on http://localhost:8501' -ForegroundColor Green; & '$python' -m chainlit run frontend/chainlit_app.py --port 8501 --host 0.0.0.0"

Write-Host ""
Write-Host "Both servers are starting..." -ForegroundColor Yellow
Write-Host "  FastAPI  → http://localhost:8000" -ForegroundColor Cyan
Write-Host "  API Docs → http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "  App      → http://localhost:8501" -ForegroundColor Green
Write-Host ""
Write-Host "Close the two opened windows to stop the servers." -ForegroundColor Gray
