try {
    $r = Invoke-WebRequest -Uri 'https://tradeforge-api.onrender.com/api/health' -UseBasicParsing -TimeoutSec 15
    Write-Host "STATUS: $($r.StatusCode)"
    Write-Host "BODY: $($r.Content)"
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Host "RESPONSE: $body"
        Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)"
    }
}