# Roteiro do vídeo (até 3 minutos)

> Grave a tela em 1080p. Antes de gravar: `python main.py seed`, deixe dois terminais abertos e o navegador em `http://127.0.0.1:8000` (com `python main.py api` rodando). Na tela do painel, cole a chave do `.env` no campo X-API-Key.

| Tempo | O que mostrar | Fala sugerida |
|---|---|---|
| **0:00 – 0:20** | `docs/fluxo_bpmn.png` | "No Luz Segura o cidadão fotografa um ponto escuro. Sem automação, alguém teria que localizar, procurar duplicado, decidir a urgência e cobrar o prazo: uns 6 minutos por relato. Nosso robô faz isso sozinho e só chama uma pessoa quando há dúvida." |
| **0:20 – 0:35** | Terminal: `python main.py seed` | "Geramos 21 cenários: relatos bons, repetidos, suspeitos e quebrados, mais um histórico com um chamado atrasado." |
| **0:35 – 1:10** | Terminal: `python main.py run` (rolar o log) | "O robô percorre o lote, um relato por vez. Aqui ele cria um P1 e dispara alerta; aqui mescla dois relatos do mesmo poste; aqui manda para revisão porque o sensor LDR mediu 42 lux e a foto dizia escuro. A Open-Meteo está fora? Ele tenta três vezes, abre o circuit breaker e segue sem travar." |
| **1:10 – 1:30** | Resumo final no terminal + pasta `data/quarentena/` com um `.motivo.json` aberto | "Nada some: o JSON corrompido, a foto que não é imagem e o relato fora do território vão para a quarentena com o motivo escrito. Erro inesperado vai para a dead letter e pode ser reprocessado." |
| **1:30 – 2:05** | Painel: mapa, fila priorizada, abrir "ver fatores" do P1 | "Essa é a integração com o MVP: o painel lê a API do robô. Cada chamado mostra por que tem aquela prioridade: sem luz, mais 40; sensor confirmou, mais 15; parada de alto fluxo, mais 15. É isso que o assistente de IA usa para explicar ao gestor." |
| **2:05 – 2:30** | Painel: revisão humana → Aprovar o S06 → Executar robô agora → novo chamado aparece | "Pessoa no circuito: o revisor aprova, o relato volta para a fila e o robô cria o chamado na hora." |
| **2:30 – 2:45** | Painel: marcar um chamado como Resolvido; KPI "tempo médio até conserto" | "A manutenção fecha o chamado e o indicador de impacto é atualizado." |
| **2:45 – 3:00** | Terminal: `python -m pytest -q` (53 passed) + `logs/luzsegura_robo.jsonl` | "53 testes cobrem sucesso, decisão e falha. Os logs são JSON, com run_id, e sem nenhum dado pessoal. Obrigado!" |

**Dica para mostrar a falha da Open-Meteo com internet ligada:** no `.env`, troque `OPEN_METEO_URL=https://api.open-meteo.invalido/v1/forecast`, rode `python main.py seed` e `python main.py run`, e depois volte o valor original.
