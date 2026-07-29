$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Sort-Object InterfaceIndex |
    Select-Object -First 1).IPAddress

if (-not $ip) {
    Write-Error "No LAN IP found."
    exit 1
}

$env:HOST_IP = $ip
docker compose run --service-ports --build zmq-publisher
