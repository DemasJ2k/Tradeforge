# Wait for deploy, then test health
Write-Host "Waiting 90s for deploy to finish..."
Start-Sleep -Seconds 90

# Test health
Write-Host "`n--- Health Check ---"
try {
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/health' -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode) BODY: $($r.Content)"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
}

# Test CORS by sending Origin header
Write-Host "`n--- CORS Test ---"
try {
    $h = @{ Origin = "https://tradeforge-tt47.onrender.com" }
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/health' -Headers $h -UseBasicParsing -TimeoutSec 15
    Write-Host "CORS headers present: $($r.Headers['Access-Control-Allow-Origin'])"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
}