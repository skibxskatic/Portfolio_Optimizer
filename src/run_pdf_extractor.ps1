# run_pdf_extractor.ps1
$ErrorActionPreference = "Stop"

Write-Host "Initializing 401k PDF Extractor..." -ForegroundColor Cyan

# 1. Activate the virtual environment
$VenvActivate = Join-Path $PSScriptRoot "..\venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
    Write-Host "Virtual environment activated." -ForegroundColor Green
}
else {
    Write-Host "Error: Virtual environment not found at $VenvActivate" -ForegroundColor Red
    Write-Host "Please run 'python -m venv venv' and install requirements first." -ForegroundColor Yellow
    Pause
    exit
}

# Ensure pypdf is installed
Write-Host "Checking for pypdf dependency..." -ForegroundColor Cyan
py -m pip install pypdf --quiet

# Setup Cache Directory
Write-Host "`nPreparing cache directory..." -ForegroundColor Cyan
$cacheDir = Join-Path $PSScriptRoot "..\Drop_Financial_Info_Here\.cache"
if (Test-Path $cacheDir) {
    Remove-Item -Path "$cacheDir\*" -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
}

# 2. Run the extraction block
try {
    Write-Host "`nScanning 'Drop_Financial_Info_Here' for 401k PDFs..." -ForegroundColor Cyan
    $pdfFiles = Get-ChildItem -Path "Drop_Financial_Info_Here" -Filter "*.pdf"
    
    if ($pdfFiles.Count -eq 0) {
        Write-Host "⚠️ No PDFs found in the 'Drop_Financial_Info_Here' folder." -ForegroundColor Yellow
        Write-Host "Please download your Fidelity NetBenefits 'Investment Options' PDF and place it in the folder first." -ForegroundColor White
    } else {
        # Find the .agent directory (should be 2 levels up in the workspace root)
        $agentDir = Join-Path $PSScriptRoot "..\..\..\.agent\skills\pdf_extraction\scripts\extract_text.py"
        
        foreach ($file in $pdfFiles) {
            Write-Host "Extracting text from: $($file.Name)..." -ForegroundColor Cyan
            # The extraction script writes output to the current working directory, 
            # so we run it from the root where the PDFs are.
            py $agentDir $file.FullName
            
            # Move the generated output to the cache directory
            $extractedFiles = Get-ChildItem -Path $PSScriptRoot\.. -Filter "extracted_text_*.txt"
            foreach ($extracted in $extractedFiles) {
                Move-Item -Path $extracted.FullName -Destination $cacheDir -Force
            }
            $extractedImages = Get-ChildItem -Path $PSScriptRoot\.. -Filter "extracted_images_*" -Directory
            foreach ($imgDir in $extractedImages) {
                Move-Item -Path $imgDir.FullName -Destination $cacheDir -Force
            }
            
            Write-Host "✅ Done with $($file.Name)" -ForegroundColor Green
        }
        Write-Host "`nAll PDFs processed and cached! You can now run the Fidelity_Optimizer.bat engine." -ForegroundColor Green
    }
}
catch {
    Write-Host "An error occurred while extracting PDF text:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Pause
}
