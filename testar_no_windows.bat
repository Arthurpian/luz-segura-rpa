@echo off
REM Testa o robo Luz Segura no Windows: instala dependencias num ambiente isolado (.venv),
REM gera os cenarios, executa o robo, testa a API e roda os 53 testes.
REM O resultado completo fica em teste_windows_resultado.txt, nesta pasta.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "LOG=%~dp0teste_windows_resultado.txt"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==== Teste Luz Segura RPA - %date% %time% ==== > "%LOG%"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version >> "%LOG%" 2>&1
if errorlevel 1 (
  echo ERRO: Python nao encontrado. Instale o Python 3.10+ em python.org e marque "Add to PATH". >> "%LOG%"
  goto fim
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Criando ambiente virtual .venv ...
  %PY% -m venv .venv >> "%LOG%" 2>&1
)
set "VPY=%~dp0.venv\Scripts\python.exe"

echo [2/5] Instalando dependencias (pode levar alguns minutos na primeira vez) ...
echo. >> "%LOG%"
echo ==== PIP INSTALL ==== >> "%LOG%"
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo ERRO na instalacao das dependencias >> "%LOG%"
  goto fim
)
if not exist ".env" copy ".env.example" ".env" >nul

echo [3/5] Gerando cenarios e executando o robo ...
echo. >> "%LOG%"
echo ==== SEED ==== >> "%LOG%"
"%VPY%" main.py seed >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ==== RUN ==== >> "%LOG%"
"%VPY%" main.py run >> "%LOG%" 2>&1

echo [4/5] Testando a API ...
echo. >> "%LOG%"
echo ==== API ==== >> "%LOG%"
"%VPY%" scripts\smoke_api.py >> "%LOG%" 2>&1

echo [5/5] Rodando os testes automatizados ...
echo. >> "%LOG%"
echo ==== PYTEST ==== >> "%LOG%"
"%VPY%" -m pytest -q -p no:cacheprovider >> "%LOG%" 2>&1

:fim
echo. >> "%LOG%"
echo ==== FIM %date% %time% ==== >> "%LOG%"
echo.
type "%LOG%"
echo.
echo Resultado salvo em teste_windows_resultado.txt
pause
