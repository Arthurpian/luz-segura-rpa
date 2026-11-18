# PDD · Process Definition Document
## Luz Segura · Triagem automática de relatos de iluminação pública

| Item | Valor |
|---|---|
| Processo | Receber relato do cidadão → validar → priorizar → abrir/atualizar chamado de manutenção |
| Dono do processo | Coordenação de manutenção da iluminação (prefeitura ou concessionária) |
| Gatilho | Agendado a cada 15 minutos (ou sob demanda: `POST /robo/executar`) |
| Tecnologia | Python 3.10+ (robô), FastAPI (API), SQLite (banco), Pillow, Requests, Pydantic |
| Volume esperado no piloto | 50 a 300 relatos/dia (bairro com ~20 paradas) |
| Versão | 1.0 |

---

### 1. Processo atual (AS-IS, manual)

| # | Passo | Quem | Tempo estimado | Problemas |
|---|---|---|---|---|
| 1 | Receber reclamação (156, e-mail, rede social) | Atendente | 1 min | Texto livre, sem foto ou sem localização |
| 2 | Descobrir o local exato no mapa | Atendente | 2 min | "Perto da padaria" · erros de endereço |
| 3 | Verificar se já existe chamado aberto | Atendente | 1,5 min | Busca por texto falha; duplicidade |
| 4 | Decidir urgência | Atendente | 0,5 min | Critério subjetivo, não auditável |
| 5 | Digitar chamado no sistema | Atendente | 1 min | Retrabalho; dados pessoais copiados sem necessidade |
| 6 | Acompanhar prazo | Supervisor | variável | Ninguém é avisado quando vence |

**Total:** cerca de 6 minutos de trabalho manual por relato (premissa configurável em `MINUTOS_MANUAIS_POR_RELATO`), sem validação física e sem rastreabilidade.

### 2. Processo automatizado (TO-BE)

Diagrama: `docs/processo_luzsegura.bpmn` · `docs/fluxo_bpmn.png`

| # | Etapa | Entrada | Regra / ação | Saída |
|---|---|---|---|---|
| 1 | Obter trava e gerar `run_id` | — | Impede execuções simultâneas | `data/.robo.lock` |
| 2 | Carregar referências | território (GeoJSON), pontos (GTFS), leituras LDR (CSV) | Território obrigatório; os demais degradam com aviso | Referências em memória |
| 3 | Coletar lote | `data/inbox/*.json` + fotos | Ordem alfabética (determinística) | Lista de arquivos |
| 4 | **Para cada relato** (repetição) | 1 arquivo | Subprocesso abaixo | Resultado por relato |
| 4.1 | Ler JSON e validar schema | arquivo | Pydantic; bloqueia *path traversal* | Relato validado ou **quarentena** |
| 4.2 | Idempotência | id + hash do conteúdo | Idêntico → ignora; diferente → `conflito_id` | — |
| 4.3 | Validar regras | relato | Dentro do território; não futuro (> 10 min); ≤ 7 dias; foto existe, ≤ 5 MB, JPG/PNG legível | — ou **quarentena** |
| 4.4 | Anonimizar (LGPD) | foto, descrição, contato | Remove EXIF/GPS; mascara e-mail/telefone/CPF/placa; contato → hash com salt | Foto limpa, texto limpo |
| 4.5 | Anti-abuso | hash do contato | > 5 relatos em 1 h → revisão | — ou **revisão** |
| 4.6 | Classificar iluminação | foto | App → API de Visão → heurística de luminância (fallback) | rótulo + confiança |
| 4.7 | Decisão de confiança | confiança | < 0,60 → revisão humana | — ou **revisão** |
| 4.8 | Decisão de iluminação | rótulo | `adequada` → improcedente | — ou **improcedente** |
| 4.9 | Validação física (LDR) | leituras | Leitura noturna a ≤ 40 m e ≤ 72 h; < 15 lux confirma, ≥ 15 contesta | confirmado / contestado / sem leitura |
| 4.10 | Enriquecer | lat/lon, horário | Open-Meteo (nuvens, visibilidade, pôr do sol); parada mais próxima (≤ 150 m); pontos sensíveis (≤ 100 m) | Contexto |
| 4.11 | Deduplicação geográfica | chamados ativos | Haversine ≤ 30 m → mescla; senão cria (verifica reincidência em 30 dias) | Chamado |
| 4.12 | Prioridade explicável + SLA | contexto | Tabela de pontos (README §4) → P1 a P4, prazo 24 h a 15 dias | `score`, `prioridade`, `motivo_prioridade`, `prazo_sla` |
| 4.13 | Gravar e auditar | tudo acima | Uma transação por relato (tudo ou nada) | Banco + auditoria |
| 4.14 | Alertar | chamado | Novo P1 ou subiu para P1 → alerta | `alertas.jsonl`, webhook, Telegram |
| 5 | Monitorar SLA (repetição) | chamados ativos | Prazo vencido → `atrasado`, +10 pontos, alerta | Chamados escalonados |
| 6 | Exportar | banco | Escrita atômica | `chamados.json`, `chamados.geojson` |
| 7 | Registrar resumo e liberar trava | contadores | — | `logs/execucoes/<run_id>.json`, tabela `execucoes` |

### 3. Exceções de negócio × exceções de sistema

| Tipo | Exemplos | Tratamento | Para onde vai |
|---|---|---|---|
| **De negócio** (dado ruim) | JSON inválido, schema, fora do território, data futura/expirada, foto ausente/corrompida/grande, conflito de id | Recusa com motivo legível | `data/quarentena/<motivo>/` + `.motivo.json` |
| **De julgamento** (dúvida) | Baixa confiança, conflito com o sensor, suspeita de abuso | Pessoa decide; se aprovar, o relato volta para a fila com o rótulo humano | `fila_revisao` (painel/API) |
| **De sistema** (temporária) | Open-Meteo, API de Visão, webhook fora do ar | Timeout, retry com backoff, circuit breaker, fallback | Relato segue; flag no chamado |
| **De sistema** (inesperada) | Bug, disco cheio, banco travado | Rollback da transação; relato isolado | `data/erros/` + `.erro.json` → `reprocessar-erros` |
| **Fatal** | Território ausente | Execução para **sem consumir** a fila | status `falhou` |

### 4. Pessoas no circuito

| Papel | Quando age | Como |
|---|---|---|
| Revisor humano | Relatos na `fila_revisao` | Painel ou `POST /revisao/{id}/decisao` (aprovar com rótulo / rejeitar) |
| Equipe de manutenção | Alerta P1 ou SLA vencido | Conserta e marca `PATCH /chamados/{id}/status` → alimenta o indicador "tempo até o conserto" |

### 5. Indicadores do processo

| Indicador | Fonte | Para que serve |
|---|---|---|
| Relatos tratados e horas manuais poupadas | `GET /indicadores` | Ganho operacional da automação |
| Taxa de mesclagem (duplicados evitados) | `relatos.resultado = mesclado` | Qualidade da fila |
| Taxa de revisão humana | `fila_revisao` | Calibração do modelo de visão e dos limiares |
| Tempo médio até o conserto | `chamados.resolvido_em - criado_em` | Impacto para o cidadão |
| Chamados atrasados | `status = atrasado` | Cumprimento de SLA |
| Execuções com erro | `execucoes.status` | Saúde do robô |

### 6. Premissas e limites

- Coordenadas e pontos de referência do piloto são simulados (documentado em `dados_simulados.py`); o formato é GTFS para troca direta por dados reais.
- O robô não substitui a vistoria: ele organiza a fila e explica a prioridade.
- Limiares (30 m, 40 m, 15 lux, 0,60, SLA) são parâmetros do `.env`, a calibrar com a operação.
