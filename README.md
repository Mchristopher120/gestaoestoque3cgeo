# Gestão de Estoque — Setor de Aprovisionamento (3º CGEO)

Sistema de estoque com a mesma identidade visual do sistema de empenhos (Flask + PostgreSQL na Vercel).

**Telas:** Painel · Estoque (cadastro, ficha/kardex) · Reposição (curva ABC, estoque de segurança, ponto de pedido) · Movimentações (entrada, saída, ajuste, estorno) · Histórico · Importar/Exportar Excel.

**Reposição (sem valores em R$):** curva ABC por quantidade consumida (A até 80%, B até 95%, C o resto); estoque de segurança = Z × σ × √L; ponto de pedido = consumo diário × L + segurança; níveis de serviço por classe ajustáveis. O prazo de entrega (L) é informado por item. O lote econômico de compra exige custos (R$) e por isso não está incluído.

**Regras:** saldo = soma das movimentações; saída nunca deixa o saldo negativo; item com movimentação só pode ser arquivado (nunca excluído); tudo fica no histórico.

## Rodar local
    pip install -r requirements.txt
    python app.py        # http://127.0.0.1:5000 (SQLite, sem senha)

## Deploy na Vercel
1. Suba esta pasta para um repositório novo no GitHub e importe na Vercel (novo projeto).
2. Crie um banco Postgres (Neon / Vercel Postgres) e adicione as variáveis:
   - `DATABASE_URL` — string de conexão do banco (use um banco **separado** do de empenhos)
   - `APP_PASSWORD` — senha do setor
   - `SECRET_KEY` — texto aleatório longo (opcional, recomendado)
3. Deploy. As tabelas são criadas sozinhas no primeiro acesso.
