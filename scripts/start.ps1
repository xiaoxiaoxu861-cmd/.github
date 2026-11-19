$root = (Resolve-Path "$PSScriptRoot\..").Path
$mysql = Join-Path $root 'mysql\bin\mysqld.exe'
$mysqlClient = Join-Path $root 'mysql\bin\mysql.exe'
$data = Join-Path $root 'mysql\data'
if (!(Test-Path $mysql)) { Write-Error '未找到 MySQL。请先执行 scripts\\setup.ps1'; exit 1 }
if (!(Test-Path $data)) { & $mysql --initialize-insecure --basedir=(Join-Path $root 'mysql') --datadir=$data }
$running = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue
if (!$running) { Start-Process -FilePath $mysql -ArgumentList "--basedir=$root\mysql","--datadir=$data","--port=3306","--bind-address=127.0.0.1","--log-error=$root\logs\mysql.log","--console" -WindowStyle Hidden }
for ($i = 0; $i -lt 20; $i++) {
  if (Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue) { break }
  Start-Sleep -Seconds 1
}
if (!(Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue)) { Write-Error 'MySQL 未能启动，请查看 logs\\mysql.log'; exit 1 }
& "$PSScriptRoot\init-db.ps1"
if (!(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath 'npm.cmd' -ArgumentList 'start' -WorkingDirectory $root -WindowStyle Hidden }
Write-Output 'MiniMall 已启动：http://localhost:3000'
