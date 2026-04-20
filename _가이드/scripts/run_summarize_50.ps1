# 인물 노트 요약 50개 일괄 실행 (시범)
# 사용법: PowerShell에서 더블클릭 또는 우클릭 -> "PowerShell로 실행"
# 또는: PowerShell에서 . .\run_summarize_50.ps1

$ErrorActionPreference = 'Continue'

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

Write-Host ""
Write-Host "===== 인물 노트 요약 시범 (50명) =====" -ForegroundColor Cyan
Write-Host ""

# API 키 (현재 세션에만, 콤마 구분 다중 키 지원)
$env:GEMINI_API_KEYS = "AIzaSyBhrNNSVWhIHauYUUtKWTw6G5kNsmrjcxI,AIzaSyBhPP8WLqckrOwi53q3MejiFDM9UucnKl0,AIzaSyCT8aS3OGrJM6yb_F_iOURrCcHz-8isGAY"
$keyCount = ($env:GEMINI_API_KEYS -split ',').Count
Write-Host ("API 키 " + $keyCount + "개 등록됨 (라운드로빈)") -ForegroundColor Green

# 스크립트 경로
$ScriptDir = "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts"
$Summarizer = Join-Path $ScriptDir "summarize_persons.py"

if (-not (Test-Path $Summarizer)) {
    Write-Host "스크립트 없음: $Summarizer" -ForegroundColor Red
    Read-Host "엔터로 종료"
    exit 1
}

Write-Host ""
Write-Host "처리 시작 (예상 시간: 약 90초, 키2개 라운드로빈, rate=1.5초)" -ForegroundColor Yellow
Write-Host "Ctrl+C 로 언제든 중단 가능. 이미 처리한 노트는 다음 실행 시 자동 스킵됨." -ForegroundColor DarkGray
Write-Host ""

$start = Get-Date

python $Summarizer --execute --side all --limit 50 --rate 1.5

$elapsed = (Get-Date) - $start
Write-Host ""
Write-Host ("===== 완료. 소요시간: {0:N1}초 =====" -f $elapsed.TotalSeconds) -ForegroundColor Cyan
Write-Host ""
Write-Host "옵시디언에서 01-인물 폴더의 최근 수정된 노트를 열어보세요." -ForegroundColor White
Write-Host ""
Read-Host "엔터를 누르면 창이 닫힙니다"
