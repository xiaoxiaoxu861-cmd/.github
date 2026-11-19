param([string]$MysqlBin = "$PSScriptRoot\..\mysql\bin\mysql.exe")
$root = (Resolve-Path "$PSScriptRoot\..").Path
& $MysqlBin -u root --protocol=TCP --port=3306 --default-character-set=utf8mb4 -e "source $root/database/schema.sql"
& $MysqlBin -u root --protocol=TCP --port=3306 --default-character-set=utf8mb4 -e "source $root/database/seed.sql"
