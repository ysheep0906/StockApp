# 커밋된 backend 를 web 서버에 배포한다.
# 실패하면 서버가 자동으로 이전 버전으로 되돌린다.
Set-Location (Split-Path $PSScriptRoot -Parent)

if (git status --porcelain) {
    Write-Host "중단: 커밋하지 않은 변경이 있습니다. 커밋한 뒤 배포하세요." -ForegroundColor Red
    git status --short
    exit 1
}

$rev = git rev-parse --short HEAD
$archive = Join-Path $env:TEMP "stockapp-$rev.tar.gz"
Write-Host "배포할 커밋: $(git log --oneline -1)"

git archive --format=tar.gz -o $archive HEAD backend
if ($LASTEXITCODE -ne 0) { Write-Host "중단: 묶기 실패" -ForegroundColor Red; exit 1 }

scp $archive "web:/tmp/stockapp-$rev.tar.gz"
if ($LASTEXITCODE -ne 0) { Write-Host "중단: 전송 실패" -ForegroundColor Red; exit 1 }
Remove-Item $archive

ssh -t web "sudo /usr/local/bin/stockapp-deploy $rev"
if ($LASTEXITCODE -ne 0) {
    Write-Host "배포 실패. 서버 로그 확인: ssh web sudo tail -20 /var/log/stockapp-deploy.log" -ForegroundColor Red
    exit 1
}
Write-Host "배포 완료: $rev" -ForegroundColor Green