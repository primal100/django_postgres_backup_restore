[CmdletBinding()]
param(
    [string]$ProjectId
)

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

    python -m pip install --upgrade pip setuptools wheel build twine "keyrings.google-artifactregistry-auth>=1.1"
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade the publishing tools and Artifact Registry keyring backend" }

    $keyringBackends = @(python -m keyring --list-backends 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not list Python keyring backends" }
    $keyringBackendText = ($keyringBackends | ForEach-Object { "$_" }) -join [Environment]::NewLine
    Write-Output $keyringBackendText
    if ($keyringBackendText -notmatch "(?i)(keyrings\.gauth\.)?GooglePythonAuth") {
        throw "The Artifact Registry keyring backend keyrings.gauth.GooglePythonAuth is not registered"
    }

    $projectId = $ProjectId
    if ([string]::IsNullOrWhiteSpace($projectId)) {
        $projectId = $env:GCP_PROJECT_ID
    }
    if (-not [string]::IsNullOrWhiteSpace($projectId)) {
        $projectId = $projectId.Trim()
    }

    $projectLookupOutput = @()
    if ([string]::IsNullOrWhiteSpace($projectId)) {
        $gcloudCommand = Get-Command gcloud -ErrorAction SilentlyContinue
        if ($null -ne $gcloudCommand) {
            $projectLookupOutput = @(
                & gcloud projects list --filter="projectNumber:910889088117" --format="value(projectId)" 2>&1
            )
            $projectLookupExitCode = $LASTEXITCODE
            if ($projectLookupExitCode -eq 0) {
                $projectIds = @(
                    $projectLookupOutput |
                        ForEach-Object { "$_".Trim() } |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
                )
                if ($projectIds.Count -eq 1) {
                    $projectId = $projectIds[0]
                }
                elseif ($projectIds.Count -gt 1) {
                    throw "More than one project matched project number 910889088117. Specify -ProjectId or set GCP_PROJECT_ID."
                }
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($projectId)) {
        $lookupDetails = ($projectLookupOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
        $message = "Could not determine the Google Cloud project ID. Pass -ProjectId, set GCP_PROJECT_ID, or install and authenticate gcloud so project number 910889088117 can be resolved."
        if (-not [string]::IsNullOrWhiteSpace($lookupDetails)) {
            $message += [Environment]::NewLine + "gcloud lookup output: " + $lookupDetails
        }
        throw $message
    }
    $repoUrl = "https://us-central1-python.pkg.dev/$projectId/private-python/"

    if (Test-Path -LiteralPath ".\dist") {
        $existingArtifacts = @(Get-ChildItem -LiteralPath ".\dist" -File)
        if ($existingArtifacts.Count -gt 0) {
            throw "dist contains old artifacts. Remove the generated dist folder before publishing to avoid uploading stale versions."
        }
    }

    python -m build
    if ($LASTEXITCODE -ne 0) { throw "python -m build failed" }

    $artifacts = @(Get-ChildItem -LiteralPath ".\dist" -File)
    $wheelArtifacts = @($artifacts | Where-Object { $_.Name -like "*.whl" })
    $sourceArtifacts = @($artifacts | Where-Object { $_.Name -like "*.tar.gz" })
    if ($artifacts.Count -ne 2 -or $wheelArtifacts.Count -ne 1 -or $sourceArtifacts.Count -ne 1) {
        throw "Expected exactly one wheel and one source distribution in dist"
    }
    $artifactPaths = @($artifacts | ForEach-Object { $_.FullName })

    python -m twine check @artifactPaths
    if ($LASTEXITCODE -ne 0) { throw "twine check failed" }

    $uploadOutput = @(
        python -m twine upload --repository-url $repoUrl --non-interactive @artifactPaths 2>&1
    )
    $uploadExitCode = $LASTEXITCODE
    if ($uploadOutput.Count -gt 0) {
        Write-Output $uploadOutput
    }
    if ($uploadExitCode -ne 0) {
        $uploadText = ($uploadOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
        if ($uploadText -match "(?i)(DefaultCredentialsError|Application Default Credentials|default credentials were not found|Could not automatically determine credentials)") {
            throw (
                "twine upload could not find Google Application Default Credentials. " +
                "Run 'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS. " +
                "Upload output: " + $uploadText
            )
        }
        throw "twine upload failed with exit code $uploadExitCode. Output: $uploadText"
    }
}
finally {
    Pop-Location
}
