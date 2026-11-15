$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
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
