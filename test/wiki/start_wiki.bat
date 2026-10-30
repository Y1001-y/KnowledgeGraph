@echo off
REM Start MediaWiki + Knowledge Graph (all local, no network needed)
cd /d "%~dp0"
REM 先把 web/ 下的前端源码部署到站点目录（首次运行或改了 graph.html 后必须）
python deploy_static.py 2>nul
cd /d "%~dp0mediawiki-1.43.1"
echo ============================================
echo   KG Wiki  http://127.0.0.1:8080
echo   Graph    http://127.0.0.1:8080/graph.html
echo   Press Ctrl+C to stop
echo ============================================
"..\php\php.exe" -S 127.0.0.1:8080 -t . "%~dp0mediawiki-1.43.1\router.php"
