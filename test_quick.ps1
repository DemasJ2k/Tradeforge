try {
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/health' -UseBasicParsing -TimeoutSec 15
    Write-Host "Health: $($r.StatusCode) - $($r.Content)"
    Write-Host "CORS: $($r.Headers['Access-Control-Allow-Origin'])"
} catch {
    Write-Host "Health ERROR: $($_.Exception.Message)"
}