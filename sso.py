"""Passagem entre os dois sistemas do setor (Aprovisionamento <-> Estoque) sem digitar a senha de novo.

Como funciona:
- Os dois sistemas guardam a MESMA chave secreta na variável SSO_SECRET (Vercel).
- Quem já entrou num sistema clica no atalho; o sistema gera um "passe" assinado com essa chave
  (nome de quem usa + para qual sistema + hora + um número aleatório) e o envia por POST ao outro.
- O outro sistema confere a assinatura, o destino, a hora (vale 60 segundos) e se o passe já foi usado.
  Estando tudo certo, abre a sessão com o mesmo nome. Sem a chave não dá para fabricar um passe.

Este arquivo é igual nos dois repositórios. Sem SSO_SECRET, o atalho só abre o outro sistema
e ele pede a senha normalmente.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

VALIDADE = 60          # segundos que um passe vale
_usados = {}           # passes já usados nesta instância -> quando podem ser esquecidos


def chave():
    return (os.environ.get("SSO_SECRET") or "").strip()


def ativo():
    return len(chave()) >= 16


def _b64(dados):
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _de_b64(texto):
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _assinar(corpo):
    return _b64(hmac.new(chave().encode(), corpo.encode(), hashlib.sha256).digest())


def gerar_passe(nome, destino):
    """destino: 'estoque' ou 'empenhos'. Devolve None quando SSO_SECRET não está configurada."""
    if not ativo() or not nome:
        return None
    dados = {"n": str(nome)[:60], "d": destino, "t": int(time.time()), "r": secrets.token_urlsafe(12)}
    corpo = _b64(json.dumps(dados, separators=(",", ":"), ensure_ascii=False).encode())
    return corpo + "." + _assinar(corpo)


def validar_passe(passe, eu):
    """eu: nome deste sistema ('estoque' ou 'empenhos'). Devolve o nome de quem entra, ou None."""
    if not ativo() or not passe or passe.count(".") != 1 or len(passe) > 600:
        return None
    corpo, assinatura = passe.split(".")
    if not hmac.compare_digest(assinatura, _assinar(corpo)):
        return None
    try:
        dados = json.loads(_de_b64(corpo))
        momento = int(dados.get("t", 0))
    except (ValueError, TypeError, AttributeError):
        return None
    agora = int(time.time())
    if dados.get("d") != eu or abs(agora - momento) > VALIDADE:
        return None
    for k, ate in list(_usados.items()):
        if ate < agora:
            del _usados[k]
    marca = str(dados.get("r") or "")
    if not marca or marca in _usados:
        return None
    _usados[marca] = agora + 2 * VALIDADE
    nome = " ".join(str(dados.get("n") or "").split())[:60]
    return nome or None
