# Evidência dos testes

Execução: `python -m pytest -v` · 2026-11-18T11:27:20 · 53 testes · 0 falhas · 0 erros · 2.95 s

Arquivos: `pytest_saida.txt` (saída completa) e `junit.xml` (formato padrão de CI).

## Sucesso (4)

| Teste | Resultado |
|---|---|
| `test_relato_valido_vira_chamado_p1_com_alerta_e_exportacao` | ✅ passou |
| `test_fluxo_completo_gera_logs_resumo_e_auditoria` | ✅ passou |
| `test_lote_com_varios_relatos_e_processado_em_ordem` | ✅ passou |
| `test_execucao_sem_relatos_conclui_sem_erro` | ✅ passou |

## Decisão (21)

| Teste | Resultado |
|---|---|
| `test_tabela_de_prioridade[ctx0-70-P1]` | ✅ passou |
| `test_tabela_de_prioridade[ctx1-61-P2]` | ✅ passou |
| `test_tabela_de_prioridade[ctx2-43-P3]` | ✅ passou |
| `test_tabela_de_prioridade[ctx3-25-P4]` | ✅ passou |
| `test_tabela_de_prioridade[ctx4-40-P3]` | ✅ passou |
| `test_tabela_de_prioridade[ctx5-100-P1]` | ✅ passou |
| `test_tabela_de_prioridade[ctx6-40-P3]` | ✅ passou |
| `test_relatos_a_menos_de_30m_sao_mesclados` | ✅ passou |
| `test_relatos_a_mais_de_30m_geram_chamados_diferentes` | ✅ passou |
| `test_recorrencia_eleva_p2_para_p1_e_dispara_alerta` | ✅ passou |
| `test_baixa_confianca_vai_para_revisao_humana` | ✅ passou |
| `test_sem_classificacao_do_app_usa_heuristica` | ✅ passou |
| `test_iluminacao_adequada_e_improcedente` | ✅ passou |
| `test_sensor_contesta_relato_e_envia_para_revisao` | ✅ passou |
| `test_leitura_diurna_do_sensor_e_ignorada` | ✅ passou |
| `test_reincidencia_soma_pontos` | ✅ passou |
| `test_sla_vencido_e_escalonado_com_alerta` | ✅ passou |
| `test_muitos_relatos_do_mesmo_contato_vao_para_revisao` | ✅ passou |
| `test_reenvio_identico_e_ignorado` | ✅ passou |
| `test_revisor_aprova_e_robo_cria_chamado_na_proxima_execucao` | ✅ passou |
| `test_revisor_rejeita_relato` | ✅ passou |

## Falha (18)

| Teste | Resultado |
|---|---|
| `test_json_corrompido_vai_para_quarentena` | ✅ passou |
| `test_schema_invalido_lista_os_campos` | ✅ passou |
| `test_tentativa_de_path_traversal_na_foto_e_bloqueada` | ✅ passou |
| `test_foto_ausente` | ✅ passou |
| `test_foto_corrompida` | ✅ passou |
| `test_fora_do_territorio` | ✅ passou |
| `test_data_futura_e_relato_expirado` | ✅ passou |
| `test_mesmo_id_com_conteudo_diferente_e_conflito` | ✅ passou |
| `test_linhas_invalidas_do_sensor_nao_derrubam_o_lote` | ✅ passou |
| `test_open_meteo_fora_do_ar_retry_circuit_breaker_e_fallback` | ✅ passou |
| `test_open_meteo_com_resposta_inesperada_usa_fallback` | ✅ passou |
| `test_api_de_visao_fora_usa_heuristica` | ✅ passou |
| `test_webhook_fora_do_ar_mantem_alerta_no_arquivo` | ✅ passou |
| `test_circuit_breaker_reabre_depois_do_tempo` | ✅ passou |
| `test_erro_inesperado_vai_para_dead_letter_e_lote_continua` | ✅ passou |
| `test_territorio_ausente_interrompe_execucao_sem_perder_relatos` | ✅ passou |
| `test_duas_execucoes_ao_mesmo_tempo_sao_bloqueadas` | ✅ passou |
| `test_trava_antiga_e_removida` | ✅ passou |

## LGPD e segurança (5)

| Teste | Resultado |
|---|---|
| `test_mascaramento_de_texto` | ✅ passou |
| `test_pseudonimizacao_e_estavel_e_irreversivel` | ✅ passou |
| `test_relato_com_pii_nao_vaza_para_banco_logs_nem_api` | ✅ passou |
| `test_exif_e_gps_sao_removidos_da_foto` | ✅ passou |
| `test_escrita_na_api_exige_chave` | ✅ passou |

## Integração com o MVP (5)

| Teste | Resultado |
|---|---|
| `test_app_envia_relato_pela_api_e_robo_processa` | ✅ passou |
| `test_detalhe_do_chamado_traz_explicacao_relatos_e_auditoria` | ✅ passou |
| `test_manutencao_resolve_chamado_e_indicador_de_conserto_e_calculado` | ✅ passou |
| `test_outro_componente_le_direto_do_banco_e_dos_arquivos` | ✅ passou |
| `test_painel_e_endpoints_de_leitura_respondem` | ✅ passou |
