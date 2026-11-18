# Contrato de integração · Robô RPA ↔ MVP Luz Segura (versão 1.0)

O robô entrega o mesmo resultado por **três canais**. Qualquer componente da CitizenTech pode usar o que for mais simples para ele.

| Canal | Endereço | Atualização | Indicado para |
|---|---|---|---|
| API REST | `http://<host>:8000` (documentação interativa em `/docs`) | tempo real | app/painel web, assistente RAG |
| Banco | `data/luzsegura.db` (SQLite) | a cada relato (transação) | pipeline de dados, BI |
| Arquivos | `data/saida/chamados.json` · `data/saida/chamados.geojson` | fim de cada execução (escrita atômica) | Airflow (camada Bronze), mapas |

---

## 1. Entrada: relato do cidadão

Gravado pelo app em `data/inbox/<nome>.json` + foto, ou enviado por `POST /relatos` (foto em base64, header `X-API-Key`).

```json
{
  "id": "33343d24-54b1-429a-acf1-513731e39687",
  "criado_em": "2026-11-17T21:00:00-03:00",
  "latitude": -23.531865,
  "longitude": -46.787873,
  "foto": "33343d24-54b1-429a-acf1-513731e39687.jpg",
  "canal": "app",
  "descricao": "Ponto do terminal completamente escuro",
  "contato": "opcional (vira hash; nunca é armazenado)",
  "classificacao_visao": { "rotulo": "inexistente", "confianca": 0.93, "fonte": "app_visao" }
}
```

| Campo | Tipo | Obrigatório | Regra |
|---|---|---|---|
| `id` | texto 8–64 (`A-Z a-z 0-9 - _`) | sim | único; reenvio idêntico é ignorado |
| `criado_em` | ISO 8601 | sim | sem fuso = horário de Brasília; não pode estar no futuro nem ter mais de 7 dias |
| `latitude`, `longitude` | número | sim | dentro do território do piloto |
| `foto` | nome de arquivo | sim | JPG/PNG, até 5 MB, sem `/` ou `..` |
| `descricao` | texto ≤ 500 | não | dados pessoais são mascarados |
| `contato` | texto ≤ 120 | não | pseudonimizado (hash com salt) |
| `canal` | `app`, `web`, `whatsapp`, `totem` | não | padrão `app` |
| `classificacao_visao` | objeto | não | se ausente, o robô chama a API de Visão ou usa o fallback |

## 2. Saída: chamado (exemplo real de `docs/exemplos/chamados.json`)

```json
{
  "id": "LS-20261118-0001",
  "status": "aberto",
  "latitude": -23.531865,
  "longitude": -46.787873,
  "rotulo_visao": "inexistente",
  "confianca_visao": 0.93,
  "validacao_ldr": "confirmado",
  "lux_medido": 2.1,
  "parada_id": "PAR-001",
  "parada_nome": "Parada Terminal Centro",
  "distancia_parada_m": 19.8,
  "fluxo_parada": "alto",
  "qtd_relatos": 3,
  "clima_indisponivel": true,
  "reincidente": false,
  "atrasado": false,
  "score": 80,
  "prioridade": "P1",
  "criado_em": "2026-11-18T11:25:13-03:00",
  "atualizado_em": "2026-11-18T11:25:18-03:00",
  "prazo_sla": "2026-11-19T11:25:13-03:00",
  "resolvido_em": null,
  "pontos_sensiveis": [],
  "motivo_prioridade": "P1 (crítica), score 80/100: Foto indica ausência de iluminação (+40); Sensor LDR confirmou baixa luminosidade (2.1 lux) (+15); A 20 m da parada PAR-001 (fluxo alto) (+15); 3 relatos para o mesmo ponto (+10)",
  "fatores_prioridade": [
    { "codigo": "severidade", "pontos": 40, "descricao": "Foto indica ausência de iluminação" },
    { "codigo": "sensor_ldr", "pontos": 15, "descricao": "Sensor LDR confirmou baixa luminosidade (2.1 lux)" },
    { "codigo": "parada_onibus", "pontos": 15, "descricao": "A 20 m da parada PAR-001 (fluxo alto)" },
    { "codigo": "recorrencia", "pontos": 10, "descricao": "3 relatos para o mesmo ponto" }
  ]
}
```

- `status`: `aberto` → `atrasado` (SLA vencido, pelo robô) → `resolvido` (pela manutenção).
- `validacao_ldr`: `confirmado`, `contestado` (só aparece após revisão humana: `revisado_humano`) ou `sem_leitura`.
- `clima_indisponivel = true` indica que a Open-Meteo estava fora e o fator climático não foi aplicado.
- `fatores_prioridade` é a explicação estruturada; o assistente RAG deve citá-la ao responder "por que este ponto está em primeiro?".
- O arquivo tem cabeçalho `{"gerado_em", "run_id", "versao_contrato": "1.0", "total", "chamados": [...]}`. O GeoJSON tem as mesmas propriedades em cada `Feature`.

## 3. Endpoints

| Método | Rota | Chave? | Descrição |
|---|---|---|---|
| GET | `/health` | não | status e última execução |
| GET | `/chamados?status=&prioridade=&limite=` | não | fila priorizada (ativos primeiro, maior score primeiro) |
| GET | `/chamados/{id}` | não | chamado + relatos vinculados + trilha de auditoria |
| GET | `/indicadores` | não | KPIs: ativos por prioridade, taxa de mesclagem, revisão, tempo até conserto, horas poupadas |
| GET | `/execucoes?limite=` | não | histórico de execuções com resumo |
| GET | `/revisao` | não | itens pendentes de revisão humana |
| GET | `/referencias` | não | território e pontos de referência (mapa) |
| POST | `/relatos` | **sim** | app envia relato (202 = na fila; 409 = já na fila) |
| POST | `/revisao/{id}/decisao` | **sim** | `{"decisao": "aprovar", "rotulo": "inexistente", "revisor": "Ana"}` ou `{"decisao": "rejeitar", ...}` |
| PATCH | `/chamados/{id}/status` | **sim** | `{"status": "resolvido", "responsavel": "Equipe 3"}` |
| POST | `/robo/executar` | **sim** | dispara uma execução (409 se já houver uma em andamento) |

Exemplo:

```bash
curl -s http://127.0.0.1:8000/chamados?prioridade=P1
curl -s -X PATCH http://127.0.0.1:8000/chamados/LS-20261118-0001/status \
     -H "X-API-Key: <chave do .env>" -H "Content-Type: application/json" \
     -d '{"status": "resolvido", "responsavel": "Equipe 3"}'
```

## 4. Tabelas do banco (SQLite)

| Tabela | Conteúdo | Chave |
|---|---|---|
| `chamados` | um registro por ponto com problema (com contexto da prioridade) | `id` (`LS-AAAAMMDD-NNNN`) |
| `relatos` | cada relato tratado, com resultado e vínculo ao chamado; contato só como hash | `id` |
| `fila_revisao` | pendências para a pessoa no circuito | `id` |
| `execucoes` | uma linha por execução do robô, com resumo JSON | `run_id` |
| `auditoria` | trilha de eventos (etapa, ação, detalhe) | `id` |

Consulta de impacto (exemplo para o pipeline de dados/BI):

```sql
SELECT prioridade,
       COUNT(*)                                                   AS chamados,
       ROUND(AVG((julianday(resolvido_em) - julianday(criado_em)) * 24), 1) AS horas_ate_conserto
FROM chamados
WHERE status = 'resolvido'
GROUP BY prioridade;
```
