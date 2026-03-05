# Login with form data (OAuth2 style)
try {
    $loginBody = "username=TradeforgeAdmin&password=admin123"
    $login = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/auth/login' -Method POST -Body $loginBody -ContentType 'application/x-www-form-urlencoded' -UseBasicParsing -TimeoutSec 15
    $token = ($login.Content | ConvertFrom-Json).access_token
    Write-Host "LOGIN OK - token starts: $($token.Substring(0,30))..."
} catch {
    Write-Host "LOGIN FAILED: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Host "RESP: $($reader.ReadToEnd())"
    }
    exit 1
}

# Test data sources
Write-Host "`n--- /api/data/sources ---"
try {
    $h = @{ Authorization = "Bearer $token" }
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/data/sources' -Headers $h -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode)"
    Write-Host "BODY: $($r.Content.Substring(0, [Math]::Min(300, $r.Content.Length)))"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)"
        Write-Host "RESP: $($reader.ReadToEnd())"
    }
}

# Test strategies
Write-Host "`n--- /api/strategies ---"
try {
    $h = @{ Authorization = "Bearer $token" }
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/strategies' -Headers $h -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode)"
    $j = $r.Content | ConvertFrom-Json
    Write-Host "Count: $($j.items.Count)"
    if ($j.items.Count -gt 0) { Write-Host "First: $($j.items[0].name)" }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)"
        Write-Host "RESP: $($reader.ReadToEnd())"
    }
}