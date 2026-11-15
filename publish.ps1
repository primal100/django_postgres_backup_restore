$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
    if (-not $env:VIRTUAL_ENV) {
        $venvPath = Join-Path $PSScriptRoot ".venv"
        $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

        if (-not (Test-Path -LiteralPath $activateScript)) {
            python -m venv $venvPath
            if ($LASTEXITCODE -ne 0) { throw "Could not create the publishing virtual environment" }
        }

        . $activateScript
    }

    $isVirtualEnv = python -c "import sys; print(sys.prefix != sys.base_prefix)"
    if ($LASTEXITCODE -ne 0 -or $isVirtualEnv.Trim() -ne "True") {
        throw "Activate a Python virtual environment before publishing"
    }

    python -m pip install --upgrade pip setuptools wheel build twine
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade the publishing tools" }

    if (Test-Path -LiteralPath ".\dist") {
        $existingArtifacts = Get-ChildItem -LiteralPath ".\dist" -File
        if ($existingArtifacts.Count -gt 0) {
            throw "dist contains old artifacts. Remove the generated dist folder before publishing to avoid uploading stale versions."
        }
    }

    python -m build
    if ($LASTEXITCODE -ne 0) { throw "python -m build failed" }

    $artifacts = Get-ChildItem -LiteralPath ".\dist" -File
    if ($artifacts.Count -ne 2) { throw "Expected one wheel and one source distribution in dist" }

    python -m twine check $artifacts.FullName
    if ($LASTEXITCODE -ne 0) { throw "twine check failed" }

    python -m twine upload $artifacts.FullName
    if ($LASTEXITCODE -ne 0) { throw "twine upload failed" }
}
finally {
    Pop-Location
}
