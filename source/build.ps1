param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$taskSource = $PSScriptRoot
$taskEnvironment = Join-Path $taskSource '.build-env'
& $Python -m venv $taskEnvironment
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 for Windows is required.' }
$taskPython = Join-Path $taskEnvironment 'Scripts\python.exe'
& $taskPython -m pip install -r (Join-Path $taskSource 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython (Join-Path $taskSource 'test_protocol.py')
if ($LASTEXITCODE -ne 0) { throw 'Protocol tests failed.' }
& $taskPython -m PyInstaller --noconfirm --onefile --windowed --name Katana-Air-Desktop --distpath (Split-Path $taskSource) --workpath (Join-Path $taskSource '.build') --specpath (Join-Path $taskSource '.build') --paths $taskSource --collect-all bleak --collect-all winrt --add-data "$taskSource\metadata.json;." --add-data "$taskSource\index.html;." (Join-Path $taskSource 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'Executable packaging failed.' }
