"""Gestão de Estoque — Setor de Aprovisionamento (3º CGEO).

Local:  SQLite (estoque.db), sem senha.
Vercel: PostgreSQL (DATABASE_URL) + senha do setor (APP_PASSWORD).
"""
import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta

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
        custo_medio {REAL} DEFAULT 0,
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
        valor_unitario {REAL} DEFAULT 0,
        custo_unit {REAL} DEFAULT 0,
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
]


def init_db():
    con = _conexao_init()
    try:
        for s in SCHEMA:
            con.execute(s)
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
    """Refaz, em ordem cronológica, o custo médio ponderado e o custo de cada
    movimento. Recusa (SaldoNegativo) qualquer histórico em que o saldo fique
    negativo — assim saídas/estornos nunca deixam o estoque inconsistente."""
    movs = db.execute(
        "SELECT id, tipo, qtde, valor_unitario, custo_unit, data FROM movimentos"
        " WHERE item_id = ? ORDER BY data, id", (item_id,)).fetchall()
    saldo, pm = 0.0, 0.0
    for m in movs:
        q = float(m["qtde"])
        if m["tipo"] == "ENTRADA":
            vu = float(m["valor_unitario"] or 0)
            novo = saldo + q
            pm = ((saldo * pm + q * vu) / novo) if novo > EPS else vu
            custo = vu
        else:
            custo = pm
        saldo += q
        if saldo < -EPS:
            raise SaldoNegativo(
                f"Saldo ficaria negativo em {fmt_data(m['data'])} ({fmt_qtd(saldo)}). "
                "Confira as datas e quantidades.")
        if abs(float(m["custo_unit"] or 0) - custo) > 1e-9:
            db.execute("UPDATE movimentos SET custo_unit = ? WHERE id = ?", (custo, m["id"]))
    db.execute("UPDATE itens SET custo_medio = ? WHERE id = ?", (pm, item_id))
    return saldo, pm


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
    d["custo_medio"] = float(d["custo_medio"] or 0)
    d["valor_total"] = round(saldo * d["custo_medio"], 2)
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
    except ValueError as e:
        return None, str(e)
    if minimo < 0 or maximo < 0:
        return None, "Estoque mínimo e máximo não podem ser negativos."
    if maximo and minimo and maximo < minimo:
        return None, "O estoque máximo não pode ser menor que o mínimo."
    return {
        "codigo": codigo, "descricao": descricao,
        "categoria": txt(data.get("categoria"), 60), "unidade": txt(data.get("unidade"), 12).upper() or "UN",
        "localizacao": txt(data.get("localizacao"), 60), "estoque_minimo": minimo, "estoque_maximo": maximo,
        "observacoes": txt(data.get("observacoes"), 500),
    }, None


def codigo_existe(db, codigo, ignorar_id=None):
    for r in db.execute("SELECT id, codigo FROM itens").fetchall():
        if sem_acento(r["codigo"]) == sem_acento(codigo) and r["id"] != ignorar_id:
            return r["id"]
    return None


def inserir_movimento(db, item_id, tipo, qtde_assinada, data, documento, contraparte, vu, obs):
    cur = db.execute(
        "INSERT INTO movimentos (item_id, tipo, qtde, data, documento, contraparte, valor_unitario,"
        " observacoes, usuario, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (item_id, tipo, qtde_assinada, data, documento, contraparte, vu, obs, usuario_atual(), agora()))
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
        custo_ini = parse_num(data.get("valor_unitario"))
        dt = parse_data(data.get("data"))
    except ValueError as e:
        return erro(str(e))
    if saldo_ini < 0 or custo_ini < 0:
        return erro("Saldo inicial e valor unitário não podem ser negativos.")
    try:
        cur = db.execute(
            "INSERT INTO itens (codigo, descricao, categoria, unidade, localizacao, estoque_minimo,"
            " estoque_maximo, custo_medio, ativo, observacoes, criado_em) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
            (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
             d["estoque_minimo"], d["estoque_maximo"], 0, d["observacoes"], agora()))
        iid = cur.lastrowid
        if saldo_ini > EPS:
            inserir_movimento(db, iid, "ENTRADA", saldo_ini, dt, "Saldo inicial", "", custo_ini, "")
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
        " estoque_maximo=?, observacoes=? WHERE id=?",
        (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
         d["estoque_minimo"], d["estoque_maximo"], d["observacoes"], iid))
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
    for r in rows:
        r["valor_total"] = round(abs(float(r["qtde"])) * float(r["valor_unitario"] if r["tipo"] == "ENTRADA" else r["custo_unit"] or 0), 2)
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
        vu = 0.0
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
                vu = parse_num(data.get("valor_unitario"))
                if vu < 0:
                    return erro("O valor unitário não pode ser negativo.")
                qtde = q
            else:
                if q > it["saldo"] + EPS:
                    return erro(f"Saldo insuficiente: há {fmt_qtd(it['saldo'])} {it['unidade']} em estoque.", 409)
                qtde = -q
    except ValueError as e:
        return erro(str(e))
    try:
        mid = inserir_movimento(db, iid, tipo, qtde, dt, doc, contra, vu, obs)
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
    movs = db.execute("SELECT item_id, tipo, qtde, data, valor_unitario, custo_unit FROM movimentos"
                      " WHERE data >= ?", (min(ini_12, ini_30),)).fetchall()
    meses = {}
    y, mth = hj.year, hj.month
    for _ in range(12):
        meses[f"{y:04d}-{mth:02d}"] = {"mes": f"{y:04d}-{mth:02d}", "entradas": 0.0, "saidas": 0.0}
        mth -= 1
        if mth == 0:
            y, mth = y - 1, 12
    saidas30, n_mes, ent_mes, sai_mes = {}, 0, 0.0, 0.0
    for m in movs:
        q = float(m["qtde"])
        if m["tipo"] == "ENTRADA":
            valor = q * float(m["valor_unitario"] or 0)
        else:
            valor = abs(q) * float(m["custo_unit"] or 0)
        chave = m["data"][:7]
        if chave in meses:
            if m["tipo"] == "ENTRADA":
                meses[chave]["entradas"] += valor
            elif m["tipo"] == "SAIDA":
                meses[chave]["saidas"] += valor
        if m["data"] >= ini_mes:
            n_mes += 1
            if m["tipo"] == "ENTRADA":
                ent_mes += valor
            elif m["tipo"] == "SAIDA":
                sai_mes += valor
        if m["tipo"] == "SAIDA" and m["data"] >= ini_30:
            s = saidas30.setdefault(m["item_id"], {"qtde": 0.0, "valor": 0.0})
            s["qtde"] += abs(q)
            s["valor"] += valor
    por_id = {i["id"]: i for i in itens}
    top_saidas = sorted(saidas30.items(), key=lambda kv: -kv[1]["valor"])[:5]
    cat = {}
    for i in ativos:
        c = i["categoria"] or "Sem categoria"
        cat[c] = cat.get(c, 0.0) + i["valor_total"]
    criticos = sorted([i for i in ativos if i["situacao"] in ("zerado", "baixo")],
                      key=lambda i: (0 if i["situacao"] == "zerado" else 1,
                                     (i["saldo"] / i["estoque_minimo"]) if i["estoque_minimo"] else 0))
    return jsonify({
        "itens_ativos": len(ativos), "itens_arquivados": len(itens) - len(ativos),
        "valor_total": round(sum(i["valor_total"] for i in ativos), 2),
        "situacao": cont,
        "movimentos_mes": n_mes, "entradas_mes": round(ent_mes, 2), "saidas_mes": round(sai_mes, 2),
        "criticos_total": len(criticos),
        "criticos": [{k: c[k] for k in ("id", "codigo", "descricao", "unidade", "saldo", "estoque_minimo",
                                          "situacao", "repor", "localizacao")} for c in criticos[:8]],
        "top_valor": [{"id": i["id"], "codigo": i["codigo"], "descricao": i["descricao"], "unidade": i["unidade"],
                       "saldo": i["saldo"], "valor_total": i["valor_total"]}
                      for i in sorted(ativos, key=lambda i: -i["valor_total"])[:5] if i["valor_total"] > 0],
        "top_saidas": [{"id": iid, "codigo": por_id[iid]["codigo"], "descricao": por_id[iid]["descricao"],
                        "unidade": por_id[iid]["unidade"], "qtde": round(s["qtde"], 3), "valor": round(s["valor"], 2)}
                       for iid, s in top_saidas if iid in por_id],
        "categorias": [{"categoria": k, "valor": round(v, 2)} for k, v in sorted(cat.items(), key=lambda kv: -kv[1])[:6] if v > 0],
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
               "Estoque máximo", "Custo médio (R$)", "Valor em estoque (R$)", "Situação", "Ativo"])
    for r in db.execute(SQL_ITENS + " ORDER BY i.descricao").fetchall():
        i = completar_item(r)
        ws.append([i["codigo"], i["descricao"], i["categoria"], i["unidade"], i["localizacao"], i["saldo"],
                   i["estoque_minimo"], i["estoque_maximo"], i["custo_medio"], i["valor_total"],
                   ROT_SIT[i["situacao"]], "Sim" if i["ativo"] else "Não"])
    for row in ws.iter_rows(min_row=2):
        for c in (row[8], row[9]):
            c.number_format = 'R$ #,##0.00'
    _estilo_planilha(ws, [14, 44, 18, 9, 16, 11, 14, 14, 16, 18, 18, 8])
    ws2 = wb.create_sheet("Movimentações")
    ws2.append(["Data", "Tipo", "Código", "Item", "Quantidade", "Unidade", "Valor unitário (R$)", "Documento",
                "Origem/Destino", "Observações", "Usuário"])
    for m in db.execute("SELECT m.*, i.codigo, i.descricao, i.unidade FROM movimentos m JOIN itens i ON i.id = m.item_id"
                        " ORDER BY m.data DESC, m.id DESC").fetchall():
        vu = m["valor_unitario"] if m["tipo"] == "ENTRADA" else m["custo_unit"]
        ws2.append([fmt_data(m["data"]), {"ENTRADA": "Entrada", "SAIDA": "Saída", "AJUSTE": "Ajuste"}[m["tipo"]],
                    m["codigo"], m["descricao"], m["qtde"], m["unidade"], vu, m["documento"], m["contraparte"],
                    m["observacoes"], m["usuario"]])
    for row in ws2.iter_rows(min_row=2):
        row[6].number_format = 'R$ #,##0.00'
    _estilo_planilha(ws2, [12, 10, 14, 44, 12, 9, 16, 16, 22, 30, 16])
    registrar(db, "EXPORTAR", "planilha", None, None, "Exportou o estoque para Excel")
    db.commit()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"estoque_{hoje()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


COLUNAS_MODELO = ["Código", "Descrição", "Categoria", "Unidade", "Localização", "Estoque mínimo",
                  "Estoque máximo", "Valor unitário", "Saldo inicial"]
ALIAS = {
    "codigo": "codigo", "cod": "codigo", "descricao": "descricao", "item": "descricao", "nome": "descricao",
    "categoria": "categoria", "grupo": "categoria", "unidade": "unidade", "und": "unidade", "un": "unidade",
    "localizacao": "localizacao", "local": "localizacao", "estoque minimo": "estoque_minimo", "minimo": "estoque_minimo",
    "estoque maximo": "estoque_maximo", "maximo": "estoque_maximo", "valor unitario": "valor_unitario",
    "valor": "valor_unitario", "custo": "valor_unitario", "preco": "valor_unitario",
    "saldo inicial": "saldo_inicial", "saldo": "saldo_inicial", "quantidade": "saldo_inicial", "qtde": "saldo_inicial",
}


@app.route("/api/importar/modelo.xlsx")
def api_modelo_importacao():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Itens"
    ws.append(COLUNAS_MODELO)
    ws.append(["PAP-A4", "Papel A4 75g (resma 500 fls)", "Material de expediente", "RESMA", "Prateleira A1", 20, 100, "27,90", 45])
    ws.append(["CAN-AZ", "Caneta esferográfica azul", "Material de expediente", "UN", "Prateleira A2", 50, 300, "1,35", 120])
    _estilo_planilha(ws, [14, 44, 24, 10, 16, 15, 15, 15, 14])
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
                                                         "estoque_minimo", "estoque_maximo")})
                if msg:
                    erros.append(f"Linha {n}: {msg}")
                    continue
                chave = sem_acento(d["codigo"])
                if chave in existentes:
                    db.execute("UPDATE itens SET descricao=?, categoria=?, unidade=?, localizacao=?, estoque_minimo=?,"
                               " estoque_maximo=? WHERE id=?",
                               (d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
                                d["estoque_minimo"], d["estoque_maximo"], existentes[chave]))
                    atualizados += 1
                else:
                    saldo, vu = parse_num(col("saldo_inicial")), parse_num(col("valor_unitario"))
                    if saldo < 0 or vu < 0:
                        erros.append(f"Linha {n}: saldo e valor não podem ser negativos.")
                        continue
                    cur = db.execute(
                        "INSERT INTO itens (codigo, descricao, categoria, unidade, localizacao, estoque_minimo,"
                        " estoque_maximo, custo_medio, ativo, observacoes, criado_em) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                        (d["codigo"], d["descricao"], d["categoria"], d["unidade"], d["localizacao"],
                         d["estoque_minimo"], d["estoque_maximo"], 0, "", agora()))
                    iid = cur.lastrowid
                    existentes[chave] = iid
                    if saldo > EPS:
                        inserir_movimento(db, iid, "ENTRADA", saldo, hoje(), "Importação", "", vu, "Saldo inicial importado")
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


# O banco é criado/migrado ao iniciar (também no Vercel, a cada cold start).
try:
    init_db()
except Exception as _e:  # banco dormindo/indisponível: as rotas mostram o aviso
    print("init_db falhou:", repr(_e), file=sys.stderr)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
