$ErrorActionPreference = 'Stop'
$appDirectory = Join-Path $PSScriptRoot 'geomap_app'
$appPython = Join-Path $PSScriptRoot '.venv313\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $appPython)) {
    $appPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
$settingsPath = Join-Path $appDirectory 'local-settings.json'
if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    foreach ($setting in $settings.PSObject.Properties) {
        if (-not [Environment]::GetEnvironmentVariable($setting.Name, 'Process')) {
            [Environment]::SetEnvironmentVariable($setting.Name, [string]$setting.Value, 'Process')
        }
    }
}
if (-not (Test-Path -LiteralPath $appPython)) {
    throw 'The local Python environment is missing. Create .venv and install geomap_app\requirements.txt first.'
}
Push-Location -LiteralPath $appDirectory
try {
    & $appPython -m streamlit run app.py @args
    if ($LASTEXITCODE -ne 0) { throw "Streamlit exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
