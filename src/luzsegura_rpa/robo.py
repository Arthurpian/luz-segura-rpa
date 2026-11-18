"""Orquestrador do robô Luz Segura.

Fluxo de uma execução (ver docs/processo_luzsegura.bpmn):

    trava -> referências -> coleta do lote -> PARA CADA relato:
        ler JSON -> validar schema -> idempotência -> validar regras (território,
        datas, foto) -> LGPD -> visão -> decisão de confiança -> decisão de
        iluminação -> sensor LDR -> clima + paradas -> deduplicação geográfica
        -> prioridade explicável + SLA -> gravação transacional -> alerta P1
    -> monitor de SLA (PARA CADA chamado ativo) -> exportação -> resumo -> libera trava

Nenhum erro de um relato derruba o lote: erro de negócio vai para
data/quarentena/<motivo>/, erro inesperado vai para data/erros/ (dead letter,
reprocessável) e tudo fica registrado em log e na tabela de auditoria.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .banco import Repositorio
from .config import Config
from .exportacao import exportar_chamados
from .geo import Territorio, carregar_pontos, haversine_m, mais_proximo
from .lgpd import higienizar_foto, mascarar_texto, pseudonimizar
from .logs import run_id_atual
from .modelos import RelatoEntrada
from .regras import (TIPOS_SENSIVEIS, ContextoPrioridade, calcular_prioridade,
                     contexto_do_chamado, pior_rotulo)
from .resiliencia import TravaExecucao
from .servicos.clima import ServicoClima
from .servicos.notificador import Notificador
from .servicos.sensores import carregar_leituras, validar_com_ldr
from .servicos.visao import ServicoVisao

log = logging.getLogger("luzsegura.robo")

EXTENSOES_FOTO = {".jpg", ".jpeg", ".png"}


class ErroDeNegocio(Exception):
    """Relato recusado por uma regra. Vai para a quarentena com o motivo."""

    def __init__(self, motivo: str, detalhe: str = "", relato_id: str | None = None, foto: str | None = None):
        super().__init__(f"{motivo}: {detalhe}")
        self.motivo = motivo
        self.detalhe = detalhe
        self.relato_id = relato_id
        self.foto = foto


class ErroFatal(Exception):
    """Falha que impede a execução inteira (ex.: território ausente)."""


@dataclass
class Resumo:
    run_id: str
    iniciado_em: str
    finalizado_em: str | None = None
    status: str = "em_andamento"
    lidos: int = 0
    chamados_criados: int = 0
    mesclados: int = 0
    improcedentes: int = 0
    revisao_humana: int = 0
    quarentena: int = 0
    duplicados_ignorados: int = 0
    erros: int = 0
    alertas: int = 0
    escalados_sla: int = 0
    clima_degradado: int = 0
    visao_degradada: int = 0
    leituras_ldr_invalidas: int = 0
    duracao_s: float = 0.0
    motivos_quarentena: dict = field(default_factory=dict)
    motivos_revisao: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Robo:
    def __init__(self, cfg: Config, clima: ServicoClima | None = None, visao: ServicoVisao | None = None,
                 notificador: Notificador | None = None, relogio: Callable[[], datetime] | None = None):
        self.cfg = cfg
        cfg.garantir_pastas()
        self.fuso = ZoneInfo(cfg.fuso)
        self.repo = Repositorio(cfg.db_path)
        self.clima = clima or ServicoClima(cfg)
        self.visao = visao or ServicoVisao(cfg)
        self.notificador = notificador or Notificador(cfg)
        self._relogio = relogio or (lambda: datetime.now(self.fuso))
        self.territorio: Territorio | None = None
        self.pontos = []
        self.leituras = []
        self.run_id = "-"
        self._motivos_q: Counter = Counter()
        self._motivos_r: Counter = Counter()

    # ================================================================ util
    def agora(self) -> datetime:
        return self._relogio().astimezone(self.fuso)

    def _iso(self, momento: datetime | None = None) -> str:
        return (momento or self.agora()).isoformat(timespec="seconds")

    def _auditar(self, etapa: str, entidade: str, entidade_id: str | None, acao: str, **detalhe) -> None:
        self.repo.auditar(self.run_id, self._iso(), etapa, entidade, entidade_id, acao, detalhe)

    def _mover(self, origem: Path, pasta: Path) -> Path | None:
        if not origem.exists():
            return None
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / origem.name
        if destino.exists():
            destino = pasta / f"{origem.stem}_{int(time.time() * 1000)}{origem.suffix}"
        shutil.move(str(origem), str(destino))
        return destino

    def _foto_referenciada(self, arquivo: Path) -> Path | None:
        """Descobre a foto citada no JSON, mesmo que o JSON seja inválido para o schema."""
        try:
            nome = json.loads(arquivo.read_text(encoding="utf-8")).get("foto")
        except (OSError, ValueError, AttributeError):
            return None
        if isinstance(nome, str) and nome and "/" not in nome and "\\" not in nome and not nome.startswith("."):
            return self.cfg.inbox / nome
        return None

    # ============================================================ execução
    def executar(self) -> Resumo:
        with TravaExecucao(self.cfg.lock_path):
            inicio = self.agora()
            self.run_id = f"RUN-{inicio:%Y%m%dT%H%M%S}-{hashlib.sha1(str(time.time_ns()).encode()).hexdigest()[:4]}"
            token = run_id_atual.set(self.run_id)
            resumo = Resumo(run_id=self.run_id, iniciado_em=self._iso(inicio))
            self._motivos_q, self._motivos_r = Counter(), Counter()
            self.repo.iniciar_execucao(self.run_id, resumo.iniciado_em)
            t0 = time.perf_counter()
            log.info("Execução iniciada", extra={"etapa": "inicio"})
            try:
                self._carregar_referencias(resumo)
                arquivos = sorted(self.cfg.inbox.glob("*.json"))
                log.info("Lote coletado: %d relato(s) na caixa de entrada", len(arquivos),
                         extra={"etapa": "coleta"})
                for posicao, arquivo in enumerate(arquivos, start=1):      # estrutura de repetição
                    resumo.lidos += 1
                    log.debug("Processando %d/%d: %s", posicao, len(arquivos), arquivo.name)
                    self._processar_com_protecao(arquivo, resumo)
                self._monitorar_sla(resumo)
                total = exportar_chamados(self.repo, self.cfg, self.run_id, self.agora())
                log.info("Exportados %d chamado(s) para data/saida (JSON e GeoJSON)", total,
                         extra={"etapa": "exportacao"})
                resumo.status = "concluida" if resumo.erros == 0 else "concluida_com_erros"
            except ErroFatal as erro:
                resumo.status = "falhou"
                log.critical("Execução interrompida: %s", erro, extra={"etapa": "inicio"})
            finally:
                resumo.duracao_s = round(time.perf_counter() - t0, 3)
                resumo.finalizado_em = self._iso()
                resumo.motivos_quarentena = dict(self._motivos_q)
                resumo.motivos_revisao = dict(self._motivos_r)
                dados = resumo.to_dict()
                dados["minutos_manuais_economizados"] = round(resumo.lidos * self.cfg.minutos_manuais_por_relato, 1)
                self.repo.finalizar_execucao(self.run_id, resumo.finalizado_em, resumo.status, dados)
                (self.cfg.execucoes / f"{self.run_id}.json").write_text(
                    json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
                log.info("Execução %s: %d lido(s), %d criado(s), %d mesclado(s), %d improcedente(s), "
                         "%d em revisão, %d em quarentena, %d duplicado(s), %d erro(s), %d alerta(s), "
                         "%d escalonado(s) por SLA em %.2fs",
                         resumo.status, resumo.lidos, resumo.chamados_criados, resumo.mesclados,
                         resumo.improcedentes, resumo.revisao_humana, resumo.quarentena,
                         resumo.duplicados_ignorados, resumo.erros, resumo.alertas, resumo.escalados_sla,
                         resumo.duracao_s, extra={"etapa": "fim", "resultado": resumo.status})
                run_id_atual.reset(token)
        return resumo

    def _carregar_referencias(self, resumo: Resumo) -> None:
        if not self.cfg.territorio_path.exists():
            raise ErroFatal(f"Arquivo de território ausente: {self.cfg.territorio_path.name}")
        try:
            self.territorio = Territorio.carregar(self.cfg.territorio_path)
        except (ValueError, KeyError) as erro:
            raise ErroFatal(f"Território inválido: {erro}") from erro

        if self.cfg.pontos_path.exists():
            self.pontos, invalidos = carregar_pontos(self.cfg.pontos_path)
            if invalidos:
                log.warning("%d ponto(s) de referência inválido(s) ignorado(s)", invalidos,
                            extra={"etapa": "referencias"})
        else:
            self.pontos = []
            log.warning("Pontos de referência ausentes: prioridade sem fator de parada/ponto sensível",
                        extra={"etapa": "referencias"})

        self.leituras, invalidas = carregar_leituras(self.cfg.ldr_path, self.cfg.fuso)
        resumo.leituras_ldr_invalidas = invalidas
        if not self.cfg.ldr_path.exists():
            log.warning("Arquivo do sensor LDR ausente: relatos seguem como 'sem_leitura'",
                        extra={"etapa": "referencias"})
        elif invalidas:
            log.warning("%d leitura(s) LDR inválida(s) descartada(s)", invalidas, extra={"etapa": "referencias"})
        log.info("Referências carregadas: território '%s', %d ponto(s), %d leitura(s) LDR",
                 self.territorio.nome, len(self.pontos), len(self.leituras), extra={"etapa": "referencias"})

    # ===================================================== por relato
    def _processar_com_protecao(self, arquivo: Path, resumo: Resumo) -> None:
        try:
            self._processar(arquivo, resumo)
        except ErroDeNegocio as erro:
            self._quarentena(arquivo, erro, resumo)
        except Exception as erro:  # noqa: BLE001 - nenhum erro pode parar o lote
            self._dead_letter(arquivo, erro, resumo)

    def _ler(self, arquivo: Path) -> dict:
        try:
            bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        except UnicodeDecodeError as erro:
            raise ErroDeNegocio("codificacao_invalida", "arquivo não está em UTF-8") from erro
        except json.JSONDecodeError as erro:
            raise ErroDeNegocio("json_invalido", f"linha {erro.lineno}, coluna {erro.colno}") from erro
        if not isinstance(bruto, dict):
            raise ErroDeNegocio("json_invalido", "o conteúdo não é um objeto JSON")
        return bruto

    def _validar_regras(self, relato: RelatoEntrada) -> Path:
        agora = self.agora()
        if not self.territorio.contem(relato.latitude, relato.longitude):
            raise ErroDeNegocio("fora_do_territorio", "coordenada fora da área do piloto", relato.id, relato.foto)
        if relato.criado_em > agora + timedelta(minutes=self.cfg.tolerancia_futuro_min):
            raise ErroDeNegocio("data_futura", "criado_em está no futuro", relato.id, relato.foto)
        if relato.criado_em < agora - timedelta(days=self.cfg.max_idade_relato_dias):
            raise ErroDeNegocio("relato_expirado", f"mais antigo que {self.cfg.max_idade_relato_dias} dias",
                                relato.id, relato.foto)
        foto = self.cfg.inbox / relato.foto
        if foto.suffix.lower() not in EXTENSOES_FOTO:
            raise ErroDeNegocio("formato_foto_nao_suportado", foto.suffix, relato.id, relato.foto)
        if not foto.exists():
            raise ErroDeNegocio("foto_ausente", relato.foto, relato.id)
        if foto.stat().st_size > self.cfg.max_foto_mb * 1024 * 1024:
            raise ErroDeNegocio("foto_muito_grande", f"limite {self.cfg.max_foto_mb} MB", relato.id, relato.foto)
        try:
            with Image.open(foto) as img:
                img.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as erro:
            raise ErroDeNegocio("foto_corrompida", "arquivo de imagem ilegível", relato.id, relato.foto) from erro
        return foto

    def _processar(self, arquivo: Path, resumo: Resumo) -> str:
        agora = self.agora()
        bruto = self._ler(arquivo)
        try:
            relato = RelatoEntrada.model_validate(bruto)
        except ValidationError as erro:
            campos = sorted({".".join(str(p) for p in e["loc"]) for e in erro.errors()})
            raise ErroDeNegocio("schema_invalido", "campos: " + ", ".join(campos),
                                bruto.get("id") if isinstance(bruto.get("id"), str) else None) from erro

        rid = relato.id
        extra = {"relato_id": rid}
        hash_conteudo = hashlib.sha256(json.dumps(bruto, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        humano = bool(relato.classificacao_visao and relato.classificacao_visao.fonte == "revisor_humano")

        # ---- Idempotência: o mesmo relato nunca gera dois chamados
        existente = self.repo.relato(rid)
        if existente:
            reprocesso = humano and existente["resultado"] == "revisao_humana"
            if not reprocesso:
                if existente["hash_conteudo"] == hash_conteudo:
                    self._mover(arquivo, self.cfg.processados / "duplicados")
                    foto = self.cfg.inbox / relato.foto
                    if foto.exists():
                        foto.unlink()
                    resumo.duplicados_ignorados += 1
                    self._auditar("idempotencia", "relato", rid, "ignorado_duplicado")
                    log.info("Relato já processado (mesmo conteúdo): ignorado", extra={**extra, "etapa": "idempotencia",
                                                                                     "resultado": "ignorado_duplicado"})
                    return "ignorado_duplicado"
                raise ErroDeNegocio("conflito_id", "mesmo id já processado com conteúdo diferente", rid, relato.foto)

        foto_entrada = self._validar_regras(relato)

        # ---- LGPD: foto sem EXIF, texto sem dados pessoais, contato só como hash
        foto_limpa = self.cfg.fotos / f"{rid}.jpg"
        info_foto = higienizar_foto(foto_entrada, foto_limpa)
        contato_hash = pseudonimizar(relato.contato, self.cfg.salt_pseudonimizacao)
        descricao = mascarar_texto(relato.descricao)
        self._auditar("lgpd", "relato", rid, "anonimizado", exif_removido=info_foto["exif_removido"],
                      pii_mascarada=descricao != relato.descricao, contato_pseudonimizado=bool(contato_hash))

        registro = {
            "id": rid, "chamado_id": None, "hash_conteudo": hash_conteudo,
            "criado_em": self._iso(relato.criado_em), "recebido_em": self._iso(agora),
            "latitude": relato.latitude, "longitude": relato.longitude, "canal": relato.canal,
            "contato_hash": contato_hash, "descricao_mascarada": descricao,
            "foto_anonimizada": foto_limpa.name, "rotulo_visao": None, "confianca_visao": None,
            "fonte_visao": None, "resultado": "", "motivo": None, "run_id": self.run_id,
        }

        # ---- Decisão anti-abuso: muitos relatos do mesmo contato em 1 hora
        if contato_hash and not humano:
            janela_ini = relato.criado_em - timedelta(hours=1)
            recentes = [r for r in self.repo.relatos_do_contato(contato_hash)
                        if r["id"] != rid and janela_ini <= datetime.fromisoformat(r["criado_em"]) <= relato.criado_em]
            if len(recentes) >= self.cfg.max_relatos_contato_hora:
                return self._revisao(arquivo, foto_entrada, registro, resumo, "suspeita_abuso",
                                     {"relatos_na_ultima_hora": len(recentes) + 1})

        # ---- Visão computacional (ou fallback)
        classificacao, degradada = self.visao.classificar(foto_limpa, relato.classificacao_visao)
        if degradada:
            resumo.visao_degradada += 1
        registro.update(rotulo_visao=classificacao.rotulo, confianca_visao=classificacao.confianca,
                        fonte_visao=classificacao.fonte)
        self._auditar("visao", "relato", rid, "classificado", rotulo=classificacao.rotulo,
                      confianca=classificacao.confianca, fonte=classificacao.fonte)

        # ---- Decisão 1: confiança suficiente?
        if classificacao.confianca < self.cfg.limiar_confianca and not humano:
            return self._revisao(arquivo, foto_entrada, registro, resumo, "baixa_confianca_visao",
                                 {"rotulo": classificacao.rotulo, "confianca": classificacao.confianca})

        # ---- Decisão 2: a foto mostra iluminação adequada?
        if classificacao.rotulo == "adequada":
            registro.update(resultado="improcedente", motivo="foto indica iluminação adequada")
            with self.repo.transacao():
                self.repo.salvar_relato(registro)
                self._auditar("decisao_iluminacao", "relato", rid, "improcedente",
                              confianca=classificacao.confianca)
            self._concluir_arquivos(arquivo, foto_entrada, "improcedentes")
            resumo.improcedentes += 1
            log.info("Iluminação adequada (%.2f): relato improcedente", classificacao.confianca,
                     extra={**extra, "etapa": "decisao_iluminacao", "resultado": "improcedente"})
            return "improcedente"

        # ---- Validação física: sensor LDR confirma ou contesta?
        status_ldr, leitura, dist_ldr = validar_com_ldr(
            relato.latitude, relato.longitude, relato.criado_em, self.leituras,
            self.cfg.raio_ldr_m, self.cfg.janela_ldr_horas, self.cfg.lux_minimo)
        self._auditar("sensor_ldr", "relato", rid, status_ldr,
                      lux=leitura.lux if leitura else None, distancia_m=round(dist_ldr, 1) if dist_ldr else None)
        if status_ldr == "contestado":
            if not humano:
                return self._revisao(arquivo, foto_entrada, registro, resumo, "conflito_sensor_ldr",
                                     {"rotulo": classificacao.rotulo, "lux_medido": leitura.lux,
                                      "dispositivo": leitura.dispositivo})
            status_ldr = "revisado_humano"

        # ---- Enriquecimento: clima e pontos de referência
        clima = self.clima.obter(relato.latitude, relato.longitude, relato.criado_em)
        if clima.indisponivel:
            resumo.clima_degradado += 1
        parada, dist_parada = mais_proximo(relato.latitude, relato.longitude, self.pontos,
                                           {"parada_onibus"}, self.cfg.raio_parada_m)
        sensiveis = sorted({p.nome for p in self.pontos if p.tipo in TIPOS_SENSIVEIS and
                            haversine_m(relato.latitude, relato.longitude, p.lat, p.lon) <= self.cfg.raio_ponto_sensivel_m})

        # ---- Decisão 3: já existe chamado aberto a até 30 m? (deduplicação geográfica)
        alvo = self._chamado_proximo(relato.latitude, relato.longitude)
        alertar = None
        with self.repo.transacao():                                         # tudo ou nada
            if alvo:
                chamado, subiu_p1 = self._mesclar(alvo, classificacao, status_ldr, leitura, agora)
                registro.update(chamado_id=chamado["id"], resultado="mesclado",
                                motivo=f"mesclado ao chamado {chamado['id']}")
                resumo.mesclados += 1
                if subiu_p1:
                    alertar = ("p1_por_recorrencia", chamado)
            else:
                chamado = self._criar(relato, classificacao, status_ldr, leitura, clima, parada, dist_parada,
                                      sensiveis, agora)
                registro.update(chamado_id=chamado["id"], resultado="chamado_criado")
                resumo.chamados_criados += 1
                if chamado["prioridade"] == "P1":
                    alertar = ("novo_p1", chamado)
            self.repo.salvar_relato(registro)
            self._auditar("persistencia", "relato", rid, registro["resultado"], chamado_id=chamado["id"])

        log.info("Relato -> chamado %s %s (%s, score %d)", chamado["id"],
                 "mesclado" if alvo else "criado", chamado["prioridade"], chamado["score"],
                 extra={**extra, "etapa": "priorizacao", "chamado_id": chamado["id"],
                        "resultado": registro["resultado"], "prioridade": chamado["prioridade"],
                        "score": chamado["score"]})

        # ---- Decisão 4: P1 dispara alerta imediato
        if alertar:
            tipo, ch = alertar
            motivo = json.loads(ch["motivo_prioridade"])["resumo"]
            canais = self.notificador.alertar(tipo, ch, f"Chamado {ch['id']} {motivo}", agora)
            resumo.alertas += 1
            self._auditar("alerta", "chamado", ch["id"], tipo, canais=canais)
            log.warning("ALERTA %s enviado (%s)", ch["id"], ", ".join(canais),
                        extra={"etapa": "alerta", "chamado_id": ch["id"], "prioridade": ch["prioridade"]})

        self._concluir_arquivos(arquivo, foto_entrada, "ok")
        return registro["resultado"]

    # ------------------------------------------------------------ apoio
    def _concluir_arquivos(self, arquivo: Path, foto: Path, subpasta: str) -> None:
        self._mover(arquivo, self.cfg.processados / subpasta)
        if foto.exists():
            foto.unlink()  # minimização: só a cópia anonimizada é mantida

    def _revisao(self, arquivo: Path, foto: Path, registro: dict, resumo: Resumo, motivo: str,
                 detalhe: dict) -> str:
        registro.update(resultado="revisao_humana", motivo=motivo)
        with self.repo.transacao():
            self.repo.salvar_relato(registro)
            revisao_id = self.repo.inserir_revisao(registro["id"], motivo, detalhe, self._iso())
            self._auditar("revisao", "relato", registro["id"], "enviado_para_revisao", motivo=motivo,
                          revisao_id=revisao_id, **detalhe)
        self._concluir_arquivos(arquivo, foto, "revisao")
        resumo.revisao_humana += 1
        self._motivos_r[motivo] += 1
        log.info("Enviado para revisão humana: %s", motivo,
                 extra={"relato_id": registro["id"], "etapa": "revisao", "resultado": "revisao_humana",
                        "motivo": motivo})
        return "revisao_humana"

    def _chamado_proximo(self, lat: float, lon: float) -> dict | None:
        melhor, melhor_d = None, None
        for ch in self.repo.chamados_ativos():                              # repetição sobre a coleção
            d = haversine_m(lat, lon, ch["latitude"], ch["longitude"])
            if d <= self.cfg.raio_deduplicacao_m and (melhor_d is None or d < melhor_d):
                melhor, melhor_d = ch, d
        return melhor

    def _reincidente(self, lat: float, lon: float, agora: datetime) -> bool:
        limite = agora - timedelta(days=self.cfg.janela_reincidencia_dias)
        for ch in self.repo.chamados_resolvidos():
            if (ch["resolvido_em"] and datetime.fromisoformat(ch["resolvido_em"]) >= limite
                    and haversine_m(lat, lon, ch["latitude"], ch["longitude"]) <= self.cfg.raio_deduplicacao_m):
                return True
        return False

    def _criar(self, relato, classificacao, status_ldr, leitura, clima, parada, dist_parada, sensiveis,
               agora) -> dict:
        ctx = ContextoPrioridade(
            rotulo=classificacao.rotulo, validacao_ldr=status_ldr,
            lux_medido=leitura.lux if leitura else None,
            parada_id=parada.id if parada else None,
            distancia_parada_m=round(dist_parada, 1) if dist_parada is not None else None,
            fluxo_parada=parada.fluxo if parada else None, pontos_sensiveis=sensiveis,
            eh_noite=clima.eh_noite, nebulosidade_pct=clima.nebulosidade_pct,
            visibilidade_m=clima.visibilidade_m,
            reincidente=self._reincidente(relato.latitude, relato.longitude, agora))
        res = calcular_prioridade(ctx)
        chamado = {
            "id": self.repo.proximo_id_chamado(agora), "status": "aberto",
            "latitude": relato.latitude, "longitude": relato.longitude,
            "rotulo_visao": classificacao.rotulo, "confianca_visao": classificacao.confianca,
            "validacao_ldr": status_ldr, "lux_medido": ctx.lux_medido,
            "parada_id": ctx.parada_id, "parada_nome": parada.nome if parada else None,
            "distancia_parada_m": ctx.distancia_parada_m, "fluxo_parada": ctx.fluxo_parada,
            "pontos_sensiveis": json.dumps(sensiveis, ensure_ascii=False), "qtd_relatos": 1,
            "eh_noite": int(clima.eh_noite), "nebulosidade_pct": clima.nebulosidade_pct,
            "visibilidade_m": clima.visibilidade_m, "clima_indisponivel": int(clima.indisponivel),
            "reincidente": int(ctx.reincidente), "atrasado": 0,
            "score": res.score, "prioridade": res.prioridade, "motivo_prioridade": res.motivo_json(),
            "criado_em": self._iso(agora), "atualizado_em": self._iso(agora),
            "prazo_sla": self._iso(agora + timedelta(hours=res.sla_horas)), "resolvido_em": None,
            "run_id_origem": self.run_id,
        }
        self.repo.inserir_chamado(chamado)
        self._auditar("priorizacao", "chamado", chamado["id"], "criado", score=res.score,
                      prioridade=res.prioridade, fatores=[f.codigo for f in res.fatores])
        return chamado

    def _mesclar(self, ch: dict, classificacao, status_ldr, leitura, agora) -> tuple[dict, bool]:
        ctx = contexto_do_chamado(ch)
        ctx.qtd_relatos += 1
        ctx.rotulo = pior_rotulo(ctx.rotulo, classificacao.rotulo)
        if status_ldr == "confirmado" and ctx.validacao_ldr != "confirmado":
            ctx.validacao_ldr, ctx.lux_medido = "confirmado", leitura.lux
        res = calcular_prioridade(ctx)
        prazo = datetime.fromisoformat(ch["criado_em"]) + timedelta(hours=res.sla_horas)
        campos = {
            "qtd_relatos": ctx.qtd_relatos, "rotulo_visao": ctx.rotulo, "validacao_ldr": ctx.validacao_ldr,
            "lux_medido": ctx.lux_medido, "score": res.score, "prioridade": res.prioridade,
            "motivo_prioridade": res.motivo_json(), "prazo_sla": self._iso(prazo),
            "atualizado_em": self._iso(agora),
        }
        self.repo.atualizar_chamado(ch["id"], **campos)
        self._auditar("deduplicacao", "chamado", ch["id"], "mesclado", qtd_relatos=ctx.qtd_relatos,
                      score_anterior=ch["score"], score_novo=res.score)
        subiu_p1 = res.prioridade == "P1" and ch["prioridade"] != "P1"
        return {**ch, **campos}, subiu_p1

    # ============================================================== SLA
    def _monitorar_sla(self, resumo: Resumo) -> None:
        agora = self.agora()
        for ch in self.repo.chamados_ativos():                              # repetição sobre a coleção
            if ch["status"] != "aberto" or datetime.fromisoformat(ch["prazo_sla"]) >= agora:
                continue
            ctx = contexto_do_chamado(ch)
            ctx.atrasado = True
            res = calcular_prioridade(ctx)
            self.repo.atualizar_chamado(ch["id"], status="atrasado", atrasado=1, score=res.score,
                                        prioridade=res.prioridade, motivo_prioridade=res.motivo_json(),
                                        atualizado_em=self._iso(agora))
            atualizado = self.repo.chamado(ch["id"])
            canais = self.notificador.alertar(
                "sla_vencido", atualizado,
                f"Chamado {ch['id']} com SLA vencido desde {ch['prazo_sla']}. {res.resumo}", agora)
            self._auditar("sla", "chamado", ch["id"], "escalonado", prioridade_anterior=ch["prioridade"],
                          prioridade_nova=res.prioridade, canais=canais)
            resumo.escalados_sla += 1
            resumo.alertas += 1
            log.warning("SLA vencido: chamado %s escalonado (%s -> %s)", ch["id"], ch["prioridade"],
                        res.prioridade, extra={"etapa": "sla", "chamado_id": ch["id"],
                                               "prioridade": res.prioridade})

    # ======================================================= exceções
    def _quarentena(self, arquivo: Path, erro: ErroDeNegocio, resumo: Resumo) -> None:
        pasta = self.cfg.quarentena / erro.motivo
        foto = self.cfg.inbox / erro.foto if erro.foto else self._foto_referenciada(arquivo)
        destino = self._mover(arquivo, pasta)
        if foto and foto.exists():
            self._mover(foto, pasta)
        ficha = {"arquivo": arquivo.name, "relato_id": erro.relato_id, "motivo": erro.motivo,
                 "detalhe": erro.detalhe, "run_id": self.run_id, "momento": self._iso()}
        if destino:
            destino.with_suffix(".motivo.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2),
                                                           encoding="utf-8")
        resumo.quarentena += 1
        self._motivos_q[erro.motivo] += 1
        self._auditar("validacao", "relato", erro.relato_id or arquivo.name, "quarentena",
                      motivo=erro.motivo, detalhe=erro.detalhe)
        log.warning("Quarentena (%s): %s", erro.motivo, erro.detalhe or arquivo.name,
                    extra={"etapa": "validacao", "relato_id": erro.relato_id, "arquivo": arquivo.name,
                           "resultado": "quarentena", "motivo": erro.motivo})

    def _dead_letter(self, arquivo: Path, erro: Exception, resumo: Resumo) -> None:
        foto = self._foto_referenciada(arquivo)
        destino = self._mover(arquivo, self.cfg.erros)
        if foto and foto.exists():
            self._mover(foto, self.cfg.erros)
        ficha = {"arquivo": arquivo.name, "tipo": type(erro).__name__,
                 "mensagem": mascarar_texto(str(erro))[:500], "run_id": self.run_id, "momento": self._iso(),
                 "como_reprocessar": "python main.py reprocessar-erros"}
        if destino:
            destino.with_suffix(".erro.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
        resumo.erros += 1
        try:
            self._auditar("erro", "relato", arquivo.name, "dead_letter", tipo=type(erro).__name__)
        except Exception:  # noqa: BLE001 - banco pode ser a causa do erro
            pass
        log.error("Erro inesperado em %s: movido para data/erros (lote continua)", arquivo.name,
                  exc_info=erro, extra={"etapa": "erro", "arquivo": arquivo.name, "resultado": "dead_letter"})


def reprocessar_erros(cfg: Config) -> int:
    """Devolve os arquivos da dead letter para a caixa de entrada."""
    total = 0
    for arq in sorted(cfg.erros.glob("*")):
        if arq.name.endswith(".erro.json"):
            arq.unlink()
            continue
        shutil.move(str(arq), str(cfg.inbox / arq.name))
        total += arq.suffix == ".json"
    return total
