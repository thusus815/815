@echo off
chcp 65001 > nul
set GEMINI_API_KEYS=AIzaSyBhrNNSVWhIHauYUUtKWTw6G5kNsmrjcxI,AIzaSyBhPP8WLqckrOwi53q3MejiFDM9UucnKl0,AIzaSyCT8aS3OGrJM6yb_F_iOURrCcHz-8isGAY
echo.
echo ============================================
echo  Gemini API 키 진단 (3개 키 x 3개 모델 = 9회 호출)
echo  소요 시간: 약 1분 (5초 간격)
echo ============================================
echo.
python -u "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts\diagnose_keys.py"
echo.
echo ============================================
echo  끝났습니다. 위 결과를 캡쳐하거나 복사해서
echo  Cursor 채팅에 붙여넣어주세요.
echo ============================================
echo.
pause
