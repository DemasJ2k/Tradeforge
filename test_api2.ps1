# Login first
try {
    $loginBody = @{ username="TradeforgeAdmin"; password="admin123" } | ConvertTo-Json
    $login = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/auth/login' -Method POST -Body $loginBody -ContentType 'application/json' -UseBasicParsing -TimeoutSec 15
    $token = ($login.Content | ConvertFrom-Json).access_token
    Write-Host "LOGIN OK - token: $($token.Substring(0,20))..."
} catch {
    Write-Host "LOGIN FAILED: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Host "RESPONSE: $($reader.ReadToEnd())"
    }
    exit 1
}

# Test /api/data/sources
Write-Host ""
Write-Host "--- Testing /api/data/sources ---"
try {
    $headers = @{ Authorization = "Bearer $token" }
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/data/sources' -Headers $headers -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode)"
    Write-Host "BODY: $($r.Content.Substring(0, [Math]::Min(500, $r.Content.Length)))"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)"
        Write-Host "RESPONSE: $body"
    }
}

# Test /api/strategies
Write-Host ""
Write-Host "--- Testing /api/strategies ---"
try {
    $headers = @{ Authorization = "Bearer $token" }
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/strategies' -Headers $headers -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode)"
    $content = $r.Content | ConvertFrom-Json
    Write-Host "Strategies count: $($content.items.Count)"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)"
        Write-Host "RESPONSE: $body"
    }
}