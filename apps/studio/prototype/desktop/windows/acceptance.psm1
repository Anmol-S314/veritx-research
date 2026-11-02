# Helpers for the native Windows acceptance job.
#
# The packaged gateway is supervised through stdin: it exits when that pipe
# closes (desktop/gateway.py, `parent_closed`). Start-Process cannot keep a pipe
# open, so the sidecar is started here through System.Diagnostics.Process with
# RedirectStandardInput left open for the lifetime of the test.

function Find-SrotaInstalledFile {
    param([Parameter(Mandatory)][string]$Name)
    $roots = @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}) |
        Where-Object { $_ -and (Test-Path $_) }
    foreach ($root in $roots) {
        $hit = Get-ChildItem -Path $root -Recurse -Filter $Name -File -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

function Start-SrotaGateway {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$DataDir,
        [int]$TimeoutSeconds = 300
    )
    if (-not (Test-Path $Path)) { throw "gateway not found: $Path" }
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Path
    $start.Arguments = '--data-dir "{0}"' -f $DataDir
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::Start($start)
    $stderr = [System.Text.StringBuilder]::new()
    $errHandler = {
        if ($EventArgs.Data) { [void]$Event.MessageData.AppendLine($EventArgs.Data) }
    }
    $errEvent = Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived `
        -Action $errHandler -MessageData $stderr
    $process.BeginErrorReadLine()

    $stdout = [System.Collections.Generic.List[string]]::new()
    $base = $null
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    try {
        $pending = $process.StandardOutput.ReadLineAsync()
        while ((Get-Date) -lt $deadline) {
            if ($process.HasExited) { break }
            if (-not $pending.Wait(1000)) { continue }
            $line = $pending.Result
            if ($null -eq $line) { break }
            $stdout.Add($line)
            if ($line.StartsWith('SROTA_READY ')) {
                $base = ($line.Substring('SROTA_READY '.Length) | ConvertFrom-Json).base
                break
            }
            $pending = $process.StandardOutput.ReadLineAsync()
        }
    } finally {
        Unregister-Event -SourceIdentifier $errEvent.Name -ErrorAction SilentlyContinue
    }

    if (-not $base) {
        $tail = if ($stderr.Length) { $stderr.ToString() } else { '(no stderr)' }
        try { $process.Kill() } catch { }
        throw "the installed gateway never announced SROTA_READY. stderr:`n$tail"
    }
    return [pscustomobject]@{
        Process = $process
        Base    = $base
        Stdout  = $stdout
        Stderr  = $stderr.ToString()
    }
}

function Stop-SrotaGateway {
    param($Gateway)
    if (-not $Gateway) { return }
    try {
        if (-not $Gateway.Process.HasExited) {
            $Gateway.Process.Kill()
            [void]$Gateway.Process.WaitForExit(15000)
        }
    } catch { }
}
