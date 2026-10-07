Remove-Item C:\eh\done.txt -ErrorAction SilentlyContinue
$env:ECHOHAMMER_UPDATE_URL = 'http://10.0.2.2:8090/latest.json'
$a = @('C:\eh\mesa.vmf', '--screenshot', 'C:\eh\upd.png', '--do', 'atualizar')
$p = Start-Process C:\eh\app\EchoHammer.exe -ArgumentList $a -PassThru
$ok = $p.WaitForExit(900000)
"exit=$($p.ExitCode) ok=$ok $(Get-Date -Format HH:mm:ss)" | Out-File C:\eh\done.txt
