"""Gestão de Estoque — Setor de Aprovisionamento (3º CGEO).

Local:  SQLite (estoque.db), sem senha.
Vercel: PostgreSQL (DATABASE_URL) + senha do setor (APP_PASSWORD).
"""
import csv
import hashlib
import hmac
import io
import math
import os
import re
import secrets
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from statistics import NormalDist

from flask import (Flask, g, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "estoque.db")

DATABASE_URL = (
    os.environ.get("DATABASE_URL", "")
    or os.environ.get("POSTGRES_URL", "")
    or os.environ.get("DATABASE_POSTGRES_URL", "")
    or os.environ.get("NEON_URL", "")
).strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

APP_PASSWORD = (os.environ.get("APP_PASSWORD") or os.environ.get("SENHA_SETOR") or "").strip()

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=USE_POSTGRES,  # produção (Vercel) é sempre HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
# A chave da sessão precisa ser a MESMA em todas as instâncias do Vercel.
app.secret_key = (
    os.environ.get("SECRET_KEY")
    or (hashlib.sha256(("estoque|" + APP_PASSWORD + "|" + DATABASE_URL).encode()).hexdigest()
        if APP_PASSWORD else secrets.token_hex(32))
)

EPS = 1e-9
TIPOS = ("ENTRADA", "SAIDA", "AJUSTE")

# ============================================================================
# Banco de dados: SQLite local / PostgreSQL em produção (mesma interface)
# ============================================================================
if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

    def _pg_connect():
        url = DATABASE_URL
        if "sslmode" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        if "connect_timeout" not in url:
            url += ("&" if "?" in url else "?") + "connect_timeout=5"
        # Neon grátis "dorme" quando ocioso: tenta de novo para absorver o wake-up.
        for tentativa in range(4):
            try:
                return psycopg.connect(url, row_factory=dict_row)
            except Exception:
                if tentativa == 3:
                    raise
                time.sleep(1 + tentativa)

    class PgCursor:
        def __init__(self, cur, lastrowid=None):
            self._cur, self.lastrowid = cur, lastrowid

        def fetchone(self):
            return self._cur.fetchone()

        def fetchall(self):
            return self._cur.fetchall()

    class PgDb:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            psql = sql.replace("?", "%s")
            cur = self.conn.cursor()
            lastrowid = None
            if psql.lstrip().upper().startswith("INSERT"):
                psql += " RETURNING id"
                cur.execute(psql, tuple(params))
                row = cur.fetchone()
                lastrowid = row["id"] if row else None
            else:
                cur.execute(psql, tuple(params))
            return PgCursor(cur, lastrowid)

        def commit(self):
            self.conn.commit()

        def rollback(self):
            self.conn.rollback()

        def close(self):
            self.conn.close()

    def get_db():
        if "db" not in g:
            g.db = PgDb(_pg_connect())
        return g.db

    def _conexao_init():
        return _pg_connect()

    PK = "SERIAL PRIMARY KEY"
    REAL = "DOUBLE PRECISION"
else:
    import sqlite3

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    def _conexao_init():
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        return con

    PK = "INTEGER PRIMARY KEY AUTOINCREMENT"
    REAL = "REAL"

SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS itens (
        id {PK},
        codigo TEXT NOT NULL,
        descricao TEXT NOT NULL,
        categoria TEXT,
        unidade TEXT,
        localizacao TEXT,
        estoque_minimo {REAL} DEFAULT 0,
        estoque_maximo {REAL} DEFAULT 0,
        prazo_entrega INTEGER DEFAULT 0,
        ativo INTEGER DEFAULT 1,
        observacoes TEXT,
        criado_em TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_itens_codigo ON itens(codigo)",
    # qtde com sinal: ENTRADA > 0, SAIDA < 0, AJUSTE +/-  (saldo = SUM(qtde))
    f"""CREATE TABLE IF NOT EXISTS movimentos (
        id {PK},
        item_id INTEGER NOT NULL REFERENCES itens(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL,
        qtde {REAL} NOT NULL,
        data TEXT NOT NULL,
        documento TEXT,
        contraparte TEXT,
        observacoes TEXT,
        usuario TEXT,
        criado_em TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_mov_item ON movimentos(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_mov_data ON movimentos(data)",
    # Auditoria sem FK de propósito: sobrevive às exclusões
    f"""CREATE TABLE IF NOT EXISTS auditoria (
        id {PK}, quando TEXT, usuario TEXT, acao TEXT, entidade TEXT,
        entidade_id INTEGER, item_id INTEGER, descricao TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS login_falhas (
        id {PK}, ip TEXT, quando TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS config (
        id {PK}, chave TEXT UNIQUE, valor TEXT)""",
]


def init_db():
    con = _conexao_init()
    try:
        for s in SCHEMA:
            con.execute(s)
        # Bancos criados em versões anteriores: acrescenta a coluna do prazo de entrega.
        if USE_POSTGRES:
            con.execute("ALTER TABLE itens ADD COLUMN IF NOT EXISTS prazo_entrega INTEGER DEFAULT 0")
        else:
            cols = [r[1] for r in con.execute("PRAGMA table_info(itens)").fetchall()]
            if "prazo_entrega" not in cols:
                con.execute("ALTER TABLE itens ADD COLUMN prazo_entrega INTEGER DEFAULT 0")
        con.commit()
    finally:
        con.close()


@app.errorhandler(500)
def erro_500(e):
    original = getattr(e, "original_exception", None) or e
    print("ERRO 500:", repr(original), file=sys.stderr)
    nome = type(original).__name__
    banco_off = "Operational" in nome or "Connection" in nome or "Timeout" in nome
    if request.path.startswith("/api/"):
        if banco_off:
            return jsonify({"erro": "banco_indisponivel",
                            "mensagem": "O banco de dados estava dormindo e está acordando. Tente de novo em alguns segundos."}), 503
        return jsonify({"erro": "erro_interno",
                        "mensagem": "Ocorreu um erro inesperado no servidor. Se persistir, avise o responsável pelo sistema."}), 500
    return render_template("erro.html", banco_off=banco_off), 503 if banco_off else 500


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ============================================================================
# Utilidades
# ============================================================================
def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje():
    return date.today().strftime("%Y-%m-%d")


def parse_num(v):
    """Aceita '1.234,56', '1234,56', '1234.56', '22.5', 'R$ 10' e números."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"R\$|\s", "", str(v))
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        if not (s.count(".") == 1 and re.search(r"\.\d{1,2}$", s)):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Número inválido: {v!r}")


def parse_data(s):
    s = (s or "").strip()
    if not s:
        return hoje()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            date(int(m[1]), int(m[2]), int(m[3]))
            return f"{m[1]}-{m[2]}-{m[3]}"
        except ValueError:
            pass
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1])).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError("Data inválida.")


def txt(v, n=200):
    return (str(v).strip() if v is not None else "")[:n]


def erro(msg, status=400):
    return jsonify({"ok": False, "error": msg}), status


def sem_acento(s):
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


# ============================================================================
# Login (senha única do setor + nome de quem usa, para o histórico)
# ============================================================================
def auth_ativa():
    return bool(APP_PASSWORD)


def usuario_atual():
    return session.get("nome") or ("local" if not auth_ativa() else "?")


ROTAS_LIVRES = {"login", "logout", "static", "favicon"}


@app.before_request
def exigir_login():
    if request.endpoint in ROTAS_LIVRES:
        return None
    if not auth_ativa():
        if USE_POSTGRES:  # em produção, sem senha = bloqueado
            if request.path.startswith("/api/"):
                return jsonify({"erro": "sem_senha", "mensagem": "Sistema sem senha configurada (APP_PASSWORD)."}), 503
            return render_template("login.html", sem_senha=True), 503
        return None
    if session.get("ok"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"erro": "nao_autenticado", "mensagem": "Sua sessão expirou. Entre novamente."}), 401
    return redirect(url_for("login", next=request.full_path if request.query_string else request.path))


def iniciais(nome):
    partes = [p for p in re.split(r"\s+", (nome or "").strip()) if p and p[0].isalpha()]
    if not partes:
        return "•"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


@app.context_processor
def contexto_templates():
    return {"usuario": session.get("nome"), "auth_ativa": auth_ativa(), "iniciais": iniciais(session.get("nome"))}


def _ip():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth_ativa():
        if USE_POSTGRES:
            return render_template("login.html", sem_senha=True), 503
        return redirect("/")
    erro_msg, nome = None, ""
    if request.method == "POST":
        db = get_db()
        nome = (request.form.get("nome") or "").strip()[:60]
        senha = request.form.get("senha") or ""
        limite = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        falhas = db.execute("SELECT COUNT(*) AS n FROM login_falhas WHERE ip = ? AND quando > ?",
                            (_ip(), limite)).fetchone()["n"]
        if falhas >= 5:
            erro_msg = "Muitas tentativas erradas. Aguarde 15 minutos e tente de novo."
        elif not nome:
            erro_msg = "Informe seu nome (ele aparece no histórico de alterações)."
        elif not hmac.compare_digest(senha.encode(), APP_PASSWORD.encode()):
            db.execute("INSERT INTO login_falhas (ip, quando) VALUES (?, ?)", (_ip(), agora()))
            db.commit()
            time.sleep(0.5)
            erro_msg = "Senha incorreta."
        else:
            session.clear()
            session.permanent = True
            session["ok"] = True
            session["nome"] = nome
            db.execute("DELETE FROM login_falhas WHERE ip = ?", (_ip(),))
            registrar(db, "LOGIN", "sessao", None, None, f"{nome} entrou no sistema")
            db.commit()
            destino = request.args.get("next") or "/"
            if not destino.startswith("/") or destino.startswith("//"):
                destino = "/"
            return redirect(destino)
    return render_template("login.html", erro=erro_msg, nome=nome)


@app.route("/favicon.ico")
def favicon():
    return send_file(os.path.join(BASE_DIR, "static", "img", "favicon.ico"),
                     mimetype="image/vnd.microsoft.icon", max_age=86400)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login") if auth_ativa() else "/")


def registrar(db, acao, entidade, entidade_id, item_id, descricao):
    db.execute(
        "INSERT INTO auditoria (quando, usuario, acao, entidade, entidade_id, item_id, descricao)"
        " VALUES (?,?,?,?,?,?,?)",
        (agora(), usuario_atual(), acao, entidade, entidade_id, item_id, descricao))


# ============================================================================
# Regras de estoque
# ============================================================================
def fmt_qtd(v):
    v = round(float(v or 0), 3)
    return str(int(v)) if v == int(v) else f"{v:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def situacao(saldo, minimo, maximo):
    """zerado > baixo (abaixo do mínimo) > excesso (acima do máximo) > ok"""
    if saldo <= EPS:
        return "zerado"
    if minimo and saldo < minimo - EPS:
        return "baixo"
    if maximo and saldo > maximo + EPS:
        return "excesso"
    return "ok"


class SaldoNegativo(ValueError):
    pass


def recalcular_item(db, item_id):
    """Confere, em ordem cronológica, que o saldo nunca fica negativo. Recusa
    (SaldoNegativo) qualquer histórico inconsistente — assim saídas e estornos
    nunca deixam o estoque errado."""
    movs = db.execute("SELECT qtde, data FROM movimentos WHERE item_id = ? ORDER BY data, id", (item_id,)).fetchall()
    saldo = 0.0
    for m in movs:
        saldo += float(m["qtde"])
        if saldo < -EPS:
            raise SaldoNegativo(
                f"Saldo ficaria negativo em {fmt_data(m['data'])} ({fmt_qtd(saldo)}). "
                "Confira as datas e quantidades.")
    return saldo


def fmt_data(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or "")
    return f"{m[3]}/{m[2]}/{m[1]}" if m else (s or "")


SQL_ITENS = """SELECT i.*, COALESCE((SELECT SUM(m.qtde) FROM movimentos m WHERE m.item_id = i.id), 0) AS saldo,
    (SELECT COUNT(*) FROM movimentos m WHERE m.item_id = i.id) AS n_mov,
    (SELECT MAX(m.data) FROM movimentos m WHERE m.item_id = i.id) AS ultima_mov
    FROM itens i"""


def completar_item(r):
    d = dict(r)
    saldo = float(d["saldo"] or 0)
    if abs(saldo) < 1e-9:
        saldo = 0.0
    minimo, maximo = float(d["estoque_minimo"] or 0), float(d["estoque_maximo"] or 0)
    d["saldo"] = round(saldo, 6)
    d["estoque_minimo"], d["estoque_maximo"] = minimo, maximo
    d["prazo_entrega"] = int(d.get("prazo_entrega") or 0)
    d["situacao"] = situacao(saldo, minimo, maximo)
    d["ativo"] = bool(d["ativo"])
    # sugestão de reposição: o que falta para chegar ao máximo (ou ao dobro do mínimo)
    alvo = maximo or (minimo * 2)
    d["repor"] = round(max(0.0, alvo - saldo), 3) if d["situacao"] in ("zerado", "baixo") and alvo else 0.0
    return d


def item_completo(db, iid):
    r = db.execute(SQL_ITENS + " WHERE i.id = ?", (iid,)).fetchone()
    return completar_item(r) if r else None


def nome_item(it):
    return f"{it['codigo']} — {it['descricao']}"


def dados_item(data):
    """Valida o corpo de criar/editar item. Devolve (dict, erro)."""
    codigo, descricao = txt(data.get("codigo"), 40), txt(data.get("descricao"), 200)
    if not codigo:
        return None, "Informe o código do item."
    if not descricao:
        return None, "Informe a descrição do item."
    try:
        minimo, maximo = parse_num(data.get("estoque_minimo")), parse_num(data.get("estoque_maximo"))
        prazo = parse_num(data.get("prazo_entrega"))
    except ValueError as e:
        return None, str(e)
    if minimo < 0 or maximo < 0:
        return None, "Estoque mínimo e máximo não podem ser negativos."
    if prazo < 0 or prazo > 365 or prazo != int(prazo):
        return None, "O prazo de entrega deve ser um número inteiro de dias (0 a 365)."
    if maximo and minimo and maximo < minimo:
        return None, "O estoque máximo não pode ser menor que o mínimo."
    return {
        "codigo": codigo, "descricao": descricao,
        "categoria": txt(data.get("categoria"), 60), "unidade": txt(data.get("unidade"), 12).upper() or "UN",
        "localizacao": txt(data.get("localizacao"), 60), "estoque_minimo": minimo, "estoque_maximo": maximo, "prazo_entrega": int(prazo),
        "observacoes": txt(data.get("observacoes"), 500),
    }, None


def codigo_existe(db, codigo, ignorar_id=None):
    for r in db.execute("SELECT id, codigo FROM itens").fetchall():
        if sem_acento(r["codigo"]) == sem_acento(codigo) and r["id"] != ignorar_id:
            return r["id"]
    return None


def inserir_movimento(db, item_id, tipo, qtde_assinada, data, documento, contraparte, obs):
    cur = db.execute(
        "INSERT INTO movimentos (item_id, tipo, qtde, data, documento, contraparte,"
        " observacoes, usuario, criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (item_id, tipo, qtde_assinada, data, documento, contraparte, obs, usuario_atual(), agora()))
    return cur.lastrowid


# ============================================================================
# Páginas
# ============================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/estoque")
def pag_estoque():
    return render_template("estoque.html")


@app.route("/movimentacoes")
def pag_movimentacoes():
    return render_template("movimentacoes.html")


@app.route("/historico")
def pag_historico():
    return render_template("historico.html")


@app.route("/importar")
def pag_importar():
    return render_template("importar.html")


# ============================================================================
# API — itens
# ============================================================================
@app.route("/api/itens")
def api_itens():
    db = get_db()
    return jsonify([completar_item(r) for r in db.execute(SQL_ITENS + " ORDER BY i.descricao").fetchall()])


@app.route("/api/itens", methods=["POST"])
def api_criar_item():
    db = get_db()
    data = request.get_json(silent=True) or {}
    d, msg = dados_item(data)
    if msg:
        return erro(msg)
    if codigo_existe(db, d["codigo"]):
        return erro(f"Já existe um item com o código {d['codigo']}.", 409)
    try:
        saldo_ini = parse_num(data.get("saldo_inicial"))
        dt = parse_data(data.get("data"))
    except ValueError as e:
        return erro(str(e))
    if saldo_ini < 0:
        return erro("O saldo inicial não pode ser negativo.")
    try:
        cur = db.execute(
            "INSERT INTO itens (codigo, descricao, categoria, unidade, localizacao, estoque_minimo,"
            " estoque_maximo, prazo_entrega, ativo, observacoes, criado_em) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
            (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
             d["estoque_minimo"], d["estoque_maximo"], d["prazo_entrega"], d["observacoes"], agora()))
        iid = cur.lastrowid
        if saldo_ini > EPS:
            inserir_movimento(db, iid, "ENTRADA", saldo_ini, dt, "Saldo inicial", "", "")
            recalcular_item(db, iid)
        registrar(db, "CRIAR", "item", iid, iid,
                  f"Cadastrou o item {d['codigo']} — {d['descricao']}"
                  + (f" com saldo inicial de {fmt_qtd(saldo_ini)} {d['unidade']}" if saldo_ini > EPS else ""))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "id": iid})


@app.route("/api/itens/<int:iid>")
def api_detalhe_item(iid):
    db = get_db()
    it = item_completo(db, iid)
    if not it:
        return erro("Item não encontrado.", 404)
    movs = [dict(r) for r in db.execute(
        "SELECT * FROM movimentos WHERE item_id = ? ORDER BY data, id", (iid,)).fetchall()]
    acc = 0.0
    for m in movs:  # kardex: saldo após cada movimento
        acc += float(m["qtde"])
        m["saldo_apos"] = round(acc, 6)
    movs.reverse()
    return jsonify({"item": it, "movimentos": movs})


@app.route("/api/itens/<int:iid>", methods=["PUT"])
def api_editar_item(iid):
    db = get_db()
    atual = item_completo(db, iid)
    if not atual:
        return erro("Item não encontrado.", 404)
    d, msg = dados_item(request.get_json(silent=True) or {})
    if msg:
        return erro(msg)
    if codigo_existe(db, d["codigo"], ignorar_id=iid):
        return erro(f"Já existe outro item com o código {d['codigo']}.", 409)
    db.execute(
        "UPDATE itens SET codigo=?, descricao=?, categoria=?, unidade=?, localizacao=?, estoque_minimo=?,"
        " estoque_maximo=?, prazo_entrega=?, observacoes=? WHERE id=?",
        (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
         d["estoque_minimo"], d["estoque_maximo"], d["prazo_entrega"], d["observacoes"], iid))
    registrar(db, "EDITAR", "item", iid, iid, f"Editou o item {d['codigo']} — {d['descricao']}")
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/itens/<int:iid>/arquivar", methods=["POST"])
def api_arquivar_item(iid):
    db = get_db()
    it = item_completo(db, iid)
    if not it:
        return erro("Item não encontrado.", 404)
    novo = 0 if it["ativo"] else 1
    if novo == 0 and it["saldo"] > EPS:
        return erro("Só é possível arquivar item com saldo zerado. Dê baixa no saldo restante antes.", 409)
    db.execute("UPDATE itens SET ativo = ? WHERE id = ?", (novo, iid))
    registrar(db, "EDITAR", "item", iid, iid, f"{'Reativou' if novo else 'Arquivou'} o item {nome_item(it)}")
    db.commit()
    return jsonify({"ok": True, "ativo": bool(novo)})


@app.route("/api/itens/<int:iid>", methods=["DELETE"])
def api_excluir_item(iid):
    db = get_db()
    it = item_completo(db, iid)
    if not it:
        return erro("Item não encontrado.", 404)
    if it["n_mov"]:
        return erro("Este item tem movimentações e não pode ser excluído. Use “Arquivar” para tirá-lo da lista.", 409)
    db.execute("DELETE FROM itens WHERE id = ?", (iid,))
    registrar(db, "EXCLUIR", "item", iid, None, f"Excluiu o item {nome_item(it)} (sem movimentações)")
    db.commit()
    return jsonify({"ok": True})


# ============================================================================
# API — movimentações
# ============================================================================
@app.route("/api/movimentos")
def api_movimentos():
    db = get_db()
    sql = ("SELECT m.*, i.codigo, i.descricao, i.unidade FROM movimentos m JOIN itens i ON i.id = m.item_id"
           " WHERE 1=1")
    p = []
    for campo, col in (("item_id", "m.item_id"), ("tipo", "m.tipo")):
        v = request.args.get(campo)
        if v:
            sql += f" AND {col} = ?"
            p.append(int(v) if campo == "item_id" else v.upper())
    if request.args.get("de"):
        sql += " AND m.data >= ?"
        p.append(request.args["de"])
    if request.args.get("ate"):
        sql += " AND m.data <= ?"
        p.append(request.args["ate"])
    try:
        limite = max(1, min(int(request.args.get("limite", 500)), 5000))
    except ValueError:
        limite = 500
    sql += f" ORDER BY m.data DESC, m.id DESC LIMIT {limite}"
    rows = [dict(r) for r in db.execute(sql, tuple(p)).fetchall()]
    return jsonify(rows)


@app.route("/api/movimentos", methods=["POST"])
def api_criar_movimento():
    db = get_db()
    data = request.get_json(silent=True) or {}
    tipo = str(data.get("tipo") or "").upper()
    if tipo not in TIPOS:
        return erro("Tipo de movimentação inválido.")
    try:
        iid = int(data.get("item_id"))
    except (TypeError, ValueError):
        return erro("Escolha o item.")
    it = item_completo(db, iid)
    if not it:
        return erro("Item não encontrado.", 404)
    if not it["ativo"]:
        return erro("Este item está arquivado. Reative-o antes de movimentar.", 409)
    try:
        dt = parse_data(data.get("data"))
        if dt > hoje():
            return erro("A data da movimentação não pode estar no futuro.")
        doc, contra, obs = txt(data.get("documento"), 60), txt(data.get("contraparte"), 100), txt(data.get("observacoes"), 300)
        if tipo == "AJUSTE":
            contado = parse_num(data.get("saldo_contado"))
            if contado < 0:
                return erro("O saldo contado não pode ser negativo.")
            qtde = contado - it["saldo"]
            if abs(qtde) < 1e-9:
                return erro("O saldo contado é igual ao saldo do sistema; nada a ajustar.")
            if not obs:
                return erro("Explique o motivo do ajuste (ex.: contagem física, avaria, perda).")
        else:
            q = parse_num(data.get("qtde"))
            if q <= 0:
                return erro("A quantidade deve ser maior que zero.")
            if tipo == "ENTRADA":
                qtde = q
            else:
                if q > it["saldo"] + EPS:
                    return erro(f"Saldo insuficiente: há {fmt_qtd(it['saldo'])} {it['unidade']} em estoque.", 409)
                qtde = -q
    except ValueError as e:
        return erro(str(e))
    try:
        mid = inserir_movimento(db, iid, tipo, qtde, dt, doc, contra, obs)
        recalcular_item(db, iid)
        rot = {"ENTRADA": "Entrada", "SAIDA": "Saída", "AJUSTE": "Ajuste"}[tipo]
        sinal = "+" if qtde > 0 else "−"
        registrar(db, tipo, "movimento", mid, iid,
                  f"{rot} de {sinal}{fmt_qtd(abs(qtde))} {it['unidade']} — {nome_item(it)}"
                  + (f" · {doc}" if doc else "") + (f" · {contra}" if contra else ""))
        db.commit()
    except SaldoNegativo as e:
        db.rollback()
        return erro(str(e), 409)
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "id": mid, "item": item_completo(db, iid)})


@app.route("/api/movimentos/<int:mid>", methods=["DELETE"])
def api_estornar_movimento(mid):
    db = get_db()
    m = db.execute("SELECT * FROM movimentos WHERE id = ?", (mid,)).fetchone()
    if not m:
        return erro("Movimentação não encontrada.", 404)
    it = item_completo(db, m["item_id"])
    try:
        db.execute("DELETE FROM movimentos WHERE id = ?", (mid,))
        recalcular_item(db, m["item_id"])
        registrar(db, "ESTORNAR", "movimento", mid, m["item_id"],
                  f"Estornou {m['tipo'].lower()} de {fmt_qtd(abs(m['qtde']))} {it['unidade']} de {fmt_data(m['data'])} — {nome_item(it)}")
        db.commit()
    except SaldoNegativo as e:
        db.rollback()
        return erro("Não dá para estornar: " + str(e), 409)
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True})


# ============================================================================
# API — painel
# ============================================================================
@app.route("/api/stats")
def api_stats():
    db = get_db()
    itens = [completar_item(r) for r in db.execute(SQL_ITENS).fetchall()]
    ativos = [i for i in itens if i["ativo"]]
    cont = {"ok": 0, "baixo": 0, "zerado": 0, "excesso": 0}
    for i in ativos:
        cont[i["situacao"]] += 1

    hj = date.today()
    ini_mes = hj.replace(day=1).strftime("%Y-%m-%d")
    ini_12 = (hj.replace(day=1) - timedelta(days=335)).replace(day=1).strftime("%Y-%m-%d")
    ini_30 = (hj - timedelta(days=30)).strftime("%Y-%m-%d")
    movs = db.execute("SELECT item_id, tipo, qtde, data FROM movimentos WHERE data >= ?",
                      (min(ini_12, ini_30),)).fetchall()
    meses = {}
    y, mth = hj.year, hj.month
    for _ in range(12):
        meses[f"{y:04d}-{mth:02d}"] = {"mes": f"{y:04d}-{mth:02d}", "entradas": 0, "saidas": 0}
        mth -= 1
        if mth == 0:
            y, mth = y - 1, 12
    saidas30, n_mes, ent_mes, sai_mes = {}, 0, 0, 0
    for m in movs:
        q = float(m["qtde"])
        chave = m["data"][:7]
        if chave in meses:
            if m["tipo"] == "ENTRADA":
                meses[chave]["entradas"] += 1
            elif m["tipo"] == "SAIDA":
                meses[chave]["saidas"] += 1
        if m["data"] >= ini_mes:
            n_mes += 1
            if m["tipo"] == "ENTRADA":
                ent_mes += 1
            elif m["tipo"] == "SAIDA":
                sai_mes += 1
        if m["tipo"] == "SAIDA" and m["data"] >= ini_30:
            saidas30[m["item_id"]] = saidas30.get(m["item_id"], 0.0) + abs(q)
    por_id = {i["id"]: i for i in itens}
    top_saidas = sorted(saidas30.items(), key=lambda kv: -kv[1])[:5]
    cat = {}
    for i in ativos:
        c = i["categoria"] or "Sem categoria"
        cat[c] = cat.get(c, 0) + 1
    criticos = sorted([i for i in ativos if i["situacao"] in ("zerado", "baixo")],
                      key=lambda i: (0 if i["situacao"] == "zerado" else 1,
                                     (i["saldo"] / i["estoque_minimo"]) if i["estoque_minimo"] else 0))
    return jsonify({
        "itens_ativos": len(ativos), "itens_arquivados": len(itens) - len(ativos),
        "situacao": cont,
        "movimentos_mes": n_mes, "entradas_mes": ent_mes, "saidas_mes": sai_mes,
        "criticos_total": len(criticos),
        "no_ponto_pedido": analise_reposicao(db)["pedir"],
        "criticos": [{k: c[k] for k in ("id", "codigo", "descricao", "unidade", "saldo", "estoque_minimo",
                                          "situacao", "repor", "localizacao")} for c in criticos[:8]],
        "top_saldo": [{"id": i["id"], "codigo": i["codigo"], "descricao": i["descricao"], "unidade": i["unidade"],
                       "saldo": i["saldo"]} for i in sorted(ativos, key=lambda i: -i["saldo"])[:5] if i["saldo"] > 0],
        "top_saidas": [{"id": iid, "codigo": por_id[iid]["codigo"], "descricao": por_id[iid]["descricao"],
                        "unidade": por_id[iid]["unidade"], "qtde": round(q, 3)}
                       for iid, q in top_saidas if iid in por_id],
        "categorias": [{"categoria": k, "itens": v} for k, v in sorted(cat.items(), key=lambda kv: -kv[1])[:6]],
        "evolucao": [meses[k] for k in sorted(meses)],
    })


@app.route("/api/alertas")
def api_alertas():
    """Leve: só o contador do menu (itens ativos zerados ou abaixo do mínimo)."""
    db = get_db()
    n = sum(1 for r in db.execute(SQL_ITENS + " WHERE i.ativo = 1").fetchall()
            if completar_item(r)["situacao"] in ("zerado", "baixo"))
    return jsonify({"repor": n})


@app.route("/api/historico")
def api_historico():
    db = get_db()
    try:
        limite = max(1, min(int(request.args.get("limite", 1000)), 5000))
    except ValueError:
        limite = 1000
    rows = db.execute(
        "SELECT a.*, i.codigo FROM auditoria a LEFT JOIN itens i ON i.id = a.item_id"
        f" ORDER BY a.id DESC LIMIT {limite}").fetchall()
    return jsonify([dict(r) for r in rows])



# ============================================================================
# Reposição: curva ABC, estoque de segurança e ponto de pedido
# ============================================================================
CONFIG_PADRAO = {"janela": 180, "ns_A": 98.0, "ns_B": 95.0, "ns_C": 90.0}
JANELAS = (30, 60, 90, 180, 365)


def ler_config(db):
    cfg = dict(CONFIG_PADRAO)
    for r in db.execute("SELECT chave, valor FROM config").fetchall():
        if r["chave"] in cfg:
            try:
                cfg[r["chave"]] = float(r["valor"])
            except (TypeError, ValueError):
                pass
    cfg["janela"] = int(cfg["janela"])
    return cfg


def _ceil(x):
    return float(math.ceil(round(x, 6)))


def analise_reposicao(db, janela=None):
    """Para cada item ativo: classe ABC (por quantidade consumida), consumo médio diário,
    estoque de segurança  SS = Z · σ · √L   e ponto de pedido  PP = d · L + SS."""
    cfg = ler_config(db)
    W = int(janela or cfg["janela"])
    hj = date.today()
    ini = (hj - timedelta(days=W - 1)).strftime("%Y-%m-%d")
    itens = [completar_item(r) for r in db.execute(SQL_ITENS + " WHERE i.ativo = 1").fetchall()]
    primeiro = {r["item_id"]: r["d"] for r in db.execute(
        "SELECT item_id, MIN(data) AS d FROM movimentos GROUP BY item_id").fetchall()}
    diario = {}
    for r in db.execute("SELECT item_id, data, qtde FROM movimentos WHERE tipo = 'SAIDA' AND data >= ?", (ini,)).fetchall():
        dd = diario.setdefault(r["item_id"], {})
        dd[r["data"]] = dd.get(r["data"], 0.0) + abs(float(r["qtde"]))

    linhas = []
    for it in itens:
        vals = list((diario.get(it["id"]) or {}).values())
        total = sum(vals)
        pri = primeiro.get(it["id"])
        hist = (hj - date.fromisoformat(pri[:10])).days + 1 if pri else 1
        n = max(1, min(W, hist))  # itens novos: só conta os dias que existem de histórico
        media = total / n
        if n > 1:
            var = max(0.0, (sum(v * v for v in vals) - n * media * media) / (n - 1))
        else:
            var = 0.0
        linhas.append({
            "id": it["id"], "codigo": it["codigo"], "descricao": it["descricao"], "unidade": it["unidade"],
            "categoria": it["categoria"], "saldo": it["saldo"], "estoque_maximo": it["estoque_maximo"],
            "prazo": it["prazo_entrega"], "consumo": round(total, 3), "dias_base": n,
            "consumo_dia": round(media, 4), "desvio_dia": round(math.sqrt(var), 4),
            "poucos_dados": n < 30,
        })

    # Curva ABC: ordena por consumo; A = até 80% acumulado, B = até 95%, C = o resto
    total_geral = sum(l["consumo"] for l in linhas) or 0.0
    acum = 0.0
    for l in sorted([x for x in linhas if x["consumo"] > 0], key=lambda x: -x["consumo"]):
        l["pct"] = l["consumo"] / total_geral * 100
        l["classe"] = "A" if acum < 80 else ("B" if acum < 95 else "C")
        acum += l["pct"]
        l["pct_acum"] = min(100.0, acum)
    for l in linhas:
        if "classe" not in l:
            l.update(classe=None, pct=0.0, pct_acum=None)

    for l in linhas:
        ns = max(50.0, min(99.9, cfg["ns_" + (l["classe"] or "C")]))
        z = NormalDist().inv_cdf(ns / 100)
        L = l["prazo"]
        ss = _ceil(z * l["desvio_dia"] * math.sqrt(L)) if L > 0 else 0.0
        pp = _ceil(l["consumo_dia"] * L + ss) if L > 0 else 0.0
        l.update(nivel_servico=ns, z=round(z, 3), seguranca=ss, ponto_pedido=pp)
        l["cobertura_dias"] = round(l["saldo"] / l["consumo_dia"], 1) if l["consumo_dia"] > 0 else None
        l["pedir"] = bool(L > 0 and l["consumo"] > 0 and l["saldo"] <= pp)
        l["qtd_sugerida"] = (_ceil(max(0.0, l["estoque_maximo"] - l["saldo"]))
                             if l["pedir"] and l["estoque_maximo"] > 0 else None)

    resumo = {}
    for c in ("A", "B", "C"):
        grupo = [l for l in linhas if l["classe"] == c]
        resumo[c] = {"itens": len(grupo),
                     "pct_consumo": round(sum(l["consumo"] for l in grupo) / total_geral * 100, 1) if total_geral else 0.0,
                     "nivel_servico": cfg["ns_" + c]}
    resumo["sem_consumo"] = len([l for l in linhas if l["classe"] is None])
    pedir_n = len([l for l in linhas if l["pedir"]])
    ordem = {"A": 0, "B": 1, "C": 2, None: 3}
    linhas.sort(key=lambda l: (ordem[l["classe"]], -l["consumo"], l["descricao"]))
    return {"janela": W, "config": cfg, "resumo": resumo, "pedir": pedir_n, "sem_prazo": len([l for l in linhas if l["prazo"] == 0 and l["consumo"] > 0]),
            "total_consumo": round(total_geral, 3), "itens": linhas}


@app.route("/reposicao")
def pag_reposicao():
    return render_template("reposicao.html")


@app.route("/api/reposicao")
def api_reposicao():
    db = get_db()
    j = request.args.get("janela", type=int)
    if j is not None and not (7 <= j <= 730):
        return erro("Período inválido (use de 7 a 730 dias).")
    return jsonify(analise_reposicao(db, j))


@app.route("/api/config", methods=["PUT"])
def api_config():
    db = get_db()
    data = request.get_json(silent=True) or {}
    novos = {}
    try:
        if "janela" in data:
            j = int(parse_num(data["janela"]))
            if not 7 <= j <= 730:
                return erro("O período de análise deve ficar entre 7 e 730 dias.")
            novos["janela"] = j
        for c in ("A", "B", "C"):
            if "ns_" + c in data:
                v = parse_num(data["ns_" + c])
                if not 50 <= v <= 99.9:
                    return erro("O nível de serviço deve ficar entre 50% e 99,9%.")
                novos["ns_" + c] = v
    except ValueError as e:
        return erro(str(e))
    for k, v in novos.items():
        if db.execute("SELECT id FROM config WHERE chave = ?", (k,)).fetchone():
            db.execute("UPDATE config SET valor = ? WHERE chave = ?", (str(v), k))
        else:
            db.execute("INSERT INTO config (chave, valor) VALUES (?, ?)", (k, str(v)))
    if novos:
        registrar(db, "EDITAR", "config", None, None, "Alterou os parâmetros de reposição: " +
                  ", ".join(f"{k}={v:g}" for k, v in novos.items()))
    db.commit()
    return jsonify({"ok": True, "config": ler_config(db)})


@app.route("/api/itens/<int:iid>/prazo", methods=["PUT"])
def api_prazo_item(iid):
    db = get_db()
    it = item_completo(db, iid)
    if not it:
        return erro("Item não encontrado.", 404)
    try:
        p = parse_num((request.get_json(silent=True) or {}).get("prazo_entrega"))
    except ValueError as e:
        return erro(str(e))
    if p < 0 or p > 365 or p != int(p):
        return erro("O prazo de entrega deve ser um número inteiro de dias (0 a 365).")
    db.execute("UPDATE itens SET prazo_entrega = ? WHERE id = ?", (int(p), iid))
    registrar(db, "EDITAR", "item", iid, iid, f"Prazo de entrega de {nome_item(it)}: {int(p)} dia(s)")
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/reposicao.xlsx")
def api_reposicao_xlsx():
    from openpyxl import Workbook
    db = get_db()
    an = analise_reposicao(db, request.args.get("janela", type=int))
    wb = Workbook()
    ws = wb.active
    ws.title = "Reposição"
    ws.append(["Classe ABC", "Código", "Item", "Unidade", "Saldo", f"Consumo ({an['janela']} dias)", "% do consumo",
               "% acumulado", "Consumo médio/dia", "Desvio/dia", "Prazo de entrega (dias)", "Nível de serviço (%)",
               "Estoque de segurança", "Ponto de pedido", "Cobertura (dias)", "Situação", "Qtd. sugerida"])
    for l in an["itens"]:
        ws.append([l["classe"] or "Sem consumo", l["codigo"], l["descricao"], l["unidade"], l["saldo"], l["consumo"],
                   round(l["pct"], 2), round(l["pct_acum"], 2) if l["pct_acum"] is not None else None,
                   l["consumo_dia"], l["desvio_dia"], l["prazo"], l["nivel_servico"], l["seguranca"], l["ponto_pedido"],
                   l["cobertura_dias"], "Pedir agora" if l["pedir"] else ("Defina o prazo" if l["prazo"] == 0 and l["consumo"] > 0 else "Ok"),
                   l["qtd_sugerida"]])
    _estilo_planilha(ws, [11, 14, 44, 9, 10, 16, 12, 12, 16, 12, 16, 16, 16, 14, 14, 16, 14])
    registrar(db, "EXPORTAR", "planilha", None, None, "Exportou a análise de reposição para Excel")
    db.commit()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"reposicao_{hoje()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ============================================================================
# Excel: exportar / modelo / importar
# ============================================================================
def _estilo_planilha(ws, larguras):
    from openpyxl.styles import Alignment, Font, PatternFill
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1A3373")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    for i, w in enumerate(larguras, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w


ROT_SIT = {"ok": "Normal", "baixo": "Abaixo do mínimo", "zerado": "Zerado", "excesso": "Acima do máximo"}


@app.route("/api/exportar.xlsx")
def api_exportar():
    from openpyxl import Workbook
    db = get_db()
    wb = Workbook()
    ws = wb.active
    ws.title = "Estoque"
    ws.append(["Código", "Descrição", "Categoria", "Unidade", "Localização", "Saldo", "Estoque mínimo",
               "Estoque máximo", "Prazo de entrega (dias)", "Situação", "Ativo"])
    for r in db.execute(SQL_ITENS + " ORDER BY i.descricao").fetchall():
        i = completar_item(r)
        ws.append([i["codigo"], i["descricao"], i["categoria"], i["unidade"], i["localizacao"], i["saldo"],
                   i["estoque_minimo"], i["estoque_maximo"], i["prazo_entrega"], ROT_SIT[i["situacao"]], "Sim" if i["ativo"] else "Não"])
    _estilo_planilha(ws, [14, 44, 18, 9, 16, 11, 14, 14, 18, 18, 8])
    ws2 = wb.create_sheet("Movimentações")
    ws2.append(["Data", "Tipo", "Código", "Item", "Quantidade", "Unidade", "Documento",
                "Origem/Destino", "Observações", "Usuário"])
    for m in db.execute("SELECT m.*, i.codigo, i.descricao, i.unidade FROM movimentos m JOIN itens i ON i.id = m.item_id"
                        " ORDER BY m.data DESC, m.id DESC").fetchall():
        ws2.append([fmt_data(m["data"]), {"ENTRADA": "Entrada", "SAIDA": "Saída", "AJUSTE": "Ajuste"}[m["tipo"]],
                    m["codigo"], m["descricao"], m["qtde"], m["unidade"], m["documento"], m["contraparte"],
                    m["observacoes"], m["usuario"]])
    _estilo_planilha(ws2, [12, 10, 14, 44, 12, 9, 16, 22, 30, 16])
    registrar(db, "EXPORTAR", "planilha", None, None, "Exportou o estoque para Excel")
    db.commit()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"estoque_{hoje()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


COLUNAS_MODELO = ["Código", "Descrição", "Categoria", "Unidade", "Localização", "Estoque mínimo",
                  "Estoque máximo", "Prazo de entrega (dias)", "Saldo inicial", "Data do saldo inicial (opcional)"]
ALIAS = {
    "codigo": "codigo", "cod": "codigo", "descricao": "descricao", "item": "descricao", "nome": "descricao",
    "categoria": "categoria", "grupo": "categoria", "unidade": "unidade", "und": "unidade", "un": "unidade",
    "localizacao": "localizacao", "local": "localizacao", "estoque minimo": "estoque_minimo", "minimo": "estoque_minimo",
    "estoque maximo": "estoque_maximo", "maximo": "estoque_maximo",
    "prazo de entrega": "prazo_entrega", "prazo": "prazo_entrega", "lead time": "prazo_entrega",
    "data do saldo inicial (opcional)": "data_saldo", "data do saldo inicial": "data_saldo", "data do saldo": "data_saldo", "data saldo": "data_saldo",
    "saldo inicial": "saldo_inicial", "saldo": "saldo_inicial", "quantidade": "saldo_inicial", "qtde": "saldo_inicial",
}


@app.route("/api/importar/modelo.xlsx")
def api_modelo_importacao():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Itens"
    ws.append(COLUNAS_MODELO)
    ws.append(["PAP-A4", "Papel A4 75g (resma 500 fls)", "Material de expediente", "RESMA", "Prateleira A1", 20, 100, 7, 45, ""])
    ws.append(["CAN-AZ", "Caneta esferográfica azul", "Material de expediente", "UN", "Prateleira A2", 50, 300, 5, 120, ""])
    _estilo_planilha(ws, [14, 44, 24, 10, 16, 15, 15, 18, 14, 20])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="modelo_importacao_estoque.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _ler_planilha(arq):
    nome = (arq.filename or "").lower()
    bruto = arq.read()
    if nome.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(bruto), read_only=True, data_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if nome.endswith(".csv"):
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = bruto.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialeto = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t")
        except csv.Error:
            dialeto = csv.excel
        return [r for r in csv.reader(io.StringIO(texto), dialeto)]
    raise ValueError("Envie um arquivo .xlsx ou .csv.")


@app.route("/api/importar", methods=["POST"])
def api_importar():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        return erro("Escolha um arquivo .xlsx ou .csv.")
    try:
        linhas = _ler_planilha(arq)
    except ValueError as e:
        return erro(str(e))
    except Exception:
        return erro("Não consegui ler o arquivo. Use o modelo para montar a planilha.")
    linhas = [l for l in linhas if l and any(c not in (None, "") for c in l)]
    if len(linhas) < 2:
        return erro("A planilha está vazia (precisa do cabeçalho e de ao menos um item).")
    mapa = {}
    for idx, cab in enumerate(linhas[0]):
        k = ALIAS.get(sem_acento(cab))
        if k and k not in mapa:
            mapa[k] = idx
    if "codigo" not in mapa or "descricao" not in mapa:
        return erro("Faltam as colunas “Código” e “Descrição”. Baixe o modelo para ver o formato.")
    if len(linhas) > 2001:
        return erro("Máximo de 2.000 itens por importação.")

    db = get_db()
    existentes = {sem_acento(r["codigo"]): r["id"] for r in db.execute("SELECT id, codigo FROM itens").fetchall()}
    criados = atualizados = 0
    erros = []
    try:
        for n, lin in enumerate(linhas[1:], start=2):
            def col(k):
                i = mapa.get(k)
                return lin[i] if i is not None and i < len(lin) else None
            try:
                d, msg = dados_item({k: col(k) for k in ("codigo", "descricao", "categoria", "unidade", "localizacao",
                                                         "estoque_minimo", "estoque_maximo", "prazo_entrega")})
                if msg:
                    erros.append(f"Linha {n}: {msg}")
                    continue
                chave = sem_acento(d["codigo"])
                if chave in existentes:
                    db.execute("UPDATE itens SET descricao=?, categoria=?, unidade=?, localizacao=?, estoque_minimo=?,"
                               " estoque_maximo=?, prazo_entrega=? WHERE id=?",
                               (d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
                                d["estoque_minimo"], d["estoque_maximo"], d["prazo_entrega"], existentes[chave]))
                    atualizados += 1
                    # Reimportar com saldo/data do saldo inicial corrige o saldo inicial, mas só se o item
                    # ainda não teve nenhuma outra movimentação (nada é reescrito no histórico real).
                    if col("saldo_inicial") not in (None, "") or col("data_saldo") not in (None, ""):
                        iid = existentes[chave]
                        movs = db.execute("SELECT id, tipo, qtde, data, observacoes FROM movimentos WHERE item_id = ?",
                                          (iid,)).fetchall()
                        if len(movs) == 1 and movs[0]["tipo"] == "ENTRADA" and movs[0]["observacoes"] == "Saldo inicial importado":
                            novo_saldo = parse_num(col("saldo_inicial")) if col("saldo_inicial") not in (None, "") else float(movs[0]["qtde"])
                            bruto = col("data_saldo")
                            if hasattr(bruto, "strftime"):
                                bruto = bruto.strftime("%Y-%m-%d")
                            nova_data = parse_data(str(bruto)) if bruto not in (None, "") else movs[0]["data"]
                            if novo_saldo <= EPS or nova_data > hoje():
                                erros.append(f"Linha {n}: saldo inicial deve ser maior que zero e a data não pode ser futura.")
                            else:
                                db.execute("UPDATE movimentos SET qtde = ?, data = ? WHERE id = ?",
                                           (novo_saldo, nova_data, movs[0]["id"]))
                                recalcular_item(db, iid)
                else:
                    saldo = parse_num(col("saldo_inicial"))
                    if saldo < 0:
                        erros.append(f"Linha {n}: o saldo não pode ser negativo.")
                        continue
                    bruto = col("data_saldo")
                    if hasattr(bruto, "strftime"):
                        bruto = bruto.strftime("%Y-%m-%d")
                    dt_saldo = parse_data(str(bruto) if bruto is not None else "")
                    if dt_saldo > hoje():
                        erros.append(f"Linha {n}: a data do saldo inicial não pode estar no futuro.")
                        continue
                    cur = db.execute(
                        "INSERT INTO itens (codigo, descricao, categoria, unidade, localizacao, estoque_minimo,"
                        " estoque_maximo, prazo_entrega, ativo, observacoes, criado_em) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                        (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
                         d["estoque_minimo"], d["estoque_maximo"], d["prazo_entrega"], "", agora()))
                    iid = cur.lastrowid
                    existentes[chave] = iid
                    if saldo > EPS:
                        inserir_movimento(db, iid, "ENTRADA", saldo, dt_saldo, "Importação", "", "Saldo inicial importado")
                        recalcular_item(db, iid)
                    criados += 1
            except ValueError as e:
                erros.append(f"Linha {n}: {e}")
        if criados or atualizados:
            registrar(db, "IMPORTAR", "planilha", None, None,
                      f"Importou planilha “{arq.filename}”: {criados} item(ns) novo(s), {atualizados} atualizado(s)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "criados": criados, "atualizados": atualizados, "erros": erros[:50], "total_erros": len(erros)})


# ============================================================================
# Saídas em lote (planilha)
# ============================================================================
COLUNAS_SAIDAS = ["Código", "Quantidade", "Data", "Documento", "Destino / requisitante", "Observações"]
ALIAS_SAIDAS = {
    "codigo": "codigo", "cod": "codigo", "item": "codigo",
    "quantidade": "qtde", "qtde": "qtde", "qtd": "qtde", "quant": "qtde",
    "data": "data", "data da saida": "data",
    "documento": "documento", "doc": "documento", "requisicao": "documento",
    "destino / requisitante": "contraparte", "destino": "contraparte", "requisitante": "contraparte",
    "setor": "contraparte", "contraparte": "contraparte",
    "observacoes": "obs", "observacao": "obs", "obs": "obs",
}


@app.route("/api/importar/saidas/modelo.xlsx")
def api_modelo_saidas():
    from openpyxl import Workbook
    db = get_db()
    itens = db.execute("SELECT id, codigo, descricao, unidade FROM itens WHERE ativo = 1 ORDER BY codigo").fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "Saídas"
    ws.append(COLUNAS_SAIDAS)
    exemplo = [(i["codigo"]) for i in itens[:2]] or ["PAP-A4", "CAN-AZ"]
    ws.append([exemplo[0], 5, hoje(), "Req 001/2026", "Seção de Pessoal", "Exemplo — apague esta linha"])
    ws.append([exemplo[-1], 20, hoje(), "Req 002/2026", "Almoxarifado", ""])
    _estilo_planilha(ws, [16, 12, 14, 18, 28, 36])
    ref = wb.create_sheet("Itens cadastrados")
    ref.append(["Código", "Descrição", "Unidade", "Saldo atual"])
    for i in itens:
        ref.append([i["codigo"], i["descricao"], i["unidade"], item_completo(db, i["id"])["saldo"]])
    _estilo_planilha(ref, [16, 46, 10, 14])
    ajuda = wb.create_sheet("Como preencher")
    ajuda.append(["Instruções"])
    for t in ("Preencha a aba “Saídas”: uma linha por saída. Só Código e Quantidade são obrigatórios.",
              "O Código precisa existir no estoque (veja a aba “Itens cadastrados”).",
              "Data: dd/mm/aaaa. Em branco = hoje. Não pode ser futura.",
              "As saídas são lançadas na ordem das linhas. Se o saldo não bastar, a linha é ignorada e o motivo aparece no resultado.",
              "Apague as linhas de exemplo antes de enviar."):
        ajuda.append([t])
    _estilo_planilha(ajuda, [110])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="modelo_saidas_estoque.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/importar/saidas", methods=["POST"])
def api_importar_saidas():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        return erro("Escolha um arquivo .xlsx ou .csv.")
    try:
        linhas = _ler_planilha(arq)
    except ValueError as e:
        return erro(str(e))
    except Exception:
        return erro("Não consegui ler o arquivo. Use o modelo de saídas para montar a planilha.")
    linhas = [l for l in linhas if l and any(c not in (None, "") for c in l)]
    if len(linhas) < 2:
        return erro("A planilha está vazia (precisa do cabeçalho e de ao menos uma saída).")
    mapa = {}
    for idx, cab in enumerate(linhas[0]):
        k = ALIAS_SAIDAS.get(sem_acento(cab))
        if k and k not in mapa:
            mapa[k] = idx
    if "codigo" not in mapa or "qtde" not in mapa:
        return erro("Faltam as colunas “Código” e “Quantidade”. Baixe o modelo de saídas para ver o formato.")
    if len(linhas) > 2001:
        return erro("Máximo de 2.000 saídas por importação.")

    db = get_db()
    por_codigo = {sem_acento(r["codigo"]): r["id"] for r in db.execute("SELECT id, codigo FROM itens").fetchall()}
    lancadas = 0
    erros = []
    try:
        for n, lin in enumerate(linhas[1:], start=2):
            def col(k):
                i = mapa.get(k)
                return lin[i] if i is not None and i < len(lin) else None
            try:
                cod = txt(col("codigo"), 60)
                iid = por_codigo.get(sem_acento(cod))
                if not iid:
                    erros.append(f"Linha {n}: código “{cod}” não encontrado.")
                    continue
                it = item_completo(db, iid)
                if not it["ativo"]:
                    erros.append(f"Linha {n}: {cod} está arquivado.")
                    continue
                q = parse_num(col("qtde"))
                if q <= 0:
                    erros.append(f"Linha {n}: a quantidade deve ser maior que zero.")
                    continue
                bruto = col("data")
                if hasattr(bruto, "strftime"):
                    bruto = bruto.strftime("%Y-%m-%d")
                dt = parse_data(str(bruto) if bruto is not None else "")
                if dt > hoje():
                    erros.append(f"Linha {n}: a data não pode estar no futuro.")
                    continue
                doc, contra, obs = txt(col("documento"), 60), txt(col("contraparte"), 100), txt(col("obs"), 300)
                mid = inserir_movimento(db, iid, "SAIDA", -q, dt, doc, contra, obs)
                try:
                    recalcular_item(db, iid)
                except SaldoNegativo:
                    db.execute("DELETE FROM movimentos WHERE id = ?", (mid,))
                    erros.append(f"Linha {n}: saldo insuficiente de {cod} para sair {fmt_qtd(q)} {it['unidade']}.")
                    continue
                registrar(db, "SAIDA", "movimento", mid, iid,
                          f"Saída de −{fmt_qtd(q)} {it['unidade']} — {nome_item(it)}"
                          + (f" · {doc}" if doc else "") + (f" · {contra}" if contra else "") + " (planilha)")
                lancadas += 1
            except ValueError as e:
                erros.append(f"Linha {n}: {e}")
        if lancadas:
            registrar(db, "IMPORTAR", "planilha", None, None,
                      f"Importou saídas da planilha “{arq.filename}”: {lancadas} lançada(s), {len(erros)} ignorada(s)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "lancadas": lancadas, "erros": erros[:50], "total_erros": len(erros)})


# O banco é criado/migrado ao iniciar (também no Vercel, a cada cold start).
try:
    init_db()
except Exception as _e:  # banco dormindo/indisponível: as rotas mostram o aviso
    print("init_db falhou:", repr(_e), file=sys.stderr)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
