if ($PSScriptRoot) {
    $dir = $PSScriptRoot
} else {
    $dir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
Start-Process python -ArgumentList "-m","http.server","8080","--directory","$dir"
Start-Process http://localhost:8080/index.html
