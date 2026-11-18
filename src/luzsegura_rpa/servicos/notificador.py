"""Alertas para a equipe de manutenção.

Sempre grava em data/saida/alertas.jsonl (trilha garantida). Se houver
webhook (Teams, Discord, n8n...) ou Telegram configurado no .env, também
envia. Falha no envio vira log de aviso, nunca falha silenciosa.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import requests

from ..config import Config

log = logging.getLogger("luzsegura.alertas")


class Notificador:
    def __init__(self, cfg: Config, sessao: requests.Session | None = None):
        self.cfg = cfg
        self.sessao = sessao or requests.Session()
        self.arquivo = cfg.saida / "alertas.jsonl"

    def alertar(self, tipo: str, chamado: dict, mensagem: str, momento: datetime) -> list[str]:
        evento = {
            "momento": momento.isoformat(timespec="seconds"),
            "tipo": tipo,
            "chamado_id": chamado["id"],
            "prioridade": chamado["prioridade"],
            "score": chamado["score"],
            "latitude": chamado["latitude"],
            "longitude": chamado["longitude"],
            "mensagem": mensagem,
        }
        canais = []
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        with self.arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        canais.append("arquivo")

        if self.cfg.webhook_alerta_url:
            try:
                self.sessao.post(self.cfg.webhook_alerta_url, json=evento,
                                 timeout=self.cfg.http_timeout_s).raise_for_status()
                canais.append("webhook")
            except requests.RequestException as erro:
                log.warning("Webhook de alerta falhou (%s); alerta mantido no arquivo",
                            type(erro).__name__, extra={"etapa": "alerta"})

        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            try:
                self.sessao.post(
                    f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                    json={"chat_id": self.cfg.telegram_chat_id, "text": f"[Luz Segura] {mensagem}"},
                    timeout=self.cfg.http_timeout_s).raise_for_status()
                canais.append("telegram")
            except requests.RequestException as erro:
                log.warning("Telegram falhou (%s); alerta mantido no arquivo",
                            type(erro).__name__, extra={"etapa": "alerta"})
        return canais
