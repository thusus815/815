# 인물 노트 요약 — 전체 일괄 (남은 모든 노트 처리)
# - 이미 요약된 노트는 자동 스킵
# - 키 3개 라운드로빈, 분당 한도 도달 시 자동 다음 키
# - 모든 키 일일 한도 도달 시 자동 종료 (다음날 다시 실행하면 이어서)
# - 진행 로그는 _가이드/scripts/_log_<날짜시간>.log 에도 저장됨

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

Write-Host ""
Write-Host "===== 인물 노트 요약 전체 실행 =====" -ForegroundColor Cyan
Write-Host ""

$env:GEMINI_API_KEYS = "AIzaSyBhrNNSVWhIHauYUUtKWTw6G5kNsmrjcxI,AIzaSyBhPP8WLqckrOwi53q3MejiFDM9UucnKl0,AIzaSyCT8aS3OGrJM6yb_F_iOURrCcHz-8isGAY"
$keyCount = ($env:GEMINI_API_KEYS -split ',').Count
Write-Host ("API 키 " + $keyCount + "개 등록됨 (라운드로빈 + 자동 재시도)") -ForegroundColor Green

$ScriptDir = "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts"
$Summarizer = Join-Path $ScriptDir "summarize_persons.py"
$LogFile = Join-Path $ScriptDir ("_log_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

if (-not (Test-Path $Summarizer)) {
    Write-Host "스크립트 없음: $Summarizer" -ForegroundColor Red
    Read-Host "엔터로 종료"
    exit 1
}

Write-Host ""
Write-Host "예상 시간: 키 " $keyCount "개 기준 무료 한도 내에서 약 1~2일에 걸쳐 자동 처리" -ForegroundColor Yellow
Write-Host "이 창을 닫으면 작업이 멈춥니다. 닫아도 되도록 백그라운드로 돌리려면 Cursor 가 알려준 명령 사용." -ForegroundColor DarkGray
Write-Host "로그 저장 위치: $LogFile" -ForegroundColor DarkGray
Write-Host ""

$start = Get-Date

# -u 플래그로 stdout 버퍼링 끄고, Tee로 로그도 동시에 저장
python -u $Summarizer --execute --side all --rate 2.0 2>&1 | Tee-Object -FilePath $LogFile

$elapsed = (Get-Date) - $start
Write-Host ""
Write-Host ("===== 끝. 소요시간: {0:N1}분 =====" -f $elapsed.TotalMinutes) -ForegroundColor Cyan
Write-Host ""
Write-Host "남은 노트가 있으면 내일 다시 실행하세요. 이미 처리된 것은 자동 스킵됩니다." -ForegroundColor White
Write-Host ""
Read-Host "엔터를 누르면 창이 닫힙니다"
