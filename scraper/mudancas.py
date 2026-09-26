"""
Compara o docs/data.json recém-gerado com a versão que está no ar e anota
em "mudancas" o que mudou (notas lançadas, faltas novas), pro painel marcar
com o selo "novo". Se NTFY_TOPIC estiver definido, também manda um push pro
celular pelo ntfy.sh com as novidades.

A versão anterior vem do próprio site publicado (PAINEL_URL/data.json), então
não precisa de Gist nem de commitar dados no repositório. Mudanças antigas
continuam no data.json por DIAS_NOVIDADE dias, pra o selo não sumir no dia
seguinte só porque nada novo foi lançado.

Uso:
    python scraper/mudancas.py                      # anterior = PAINEL_URL
    python scraper/mudancas.py --anterior velho.json --sem-aviso
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "docs" / "data.json"
BRASILIA = timezone(timedelta(hours=-3))
DIAS_NOVIDADE = 7

COMPONENTES = ["a1", "a2", "at", "bs", "be", "ar", "mb"]
NOME_COMP = {"a1": "A1", "a2": "A2", "at": "AT", "bs": "Bônus", "be": "Bônus extra",
             "ar": "Recuperação", "mb": "Média"}
CAMPOS_FINAIS = {"exame_final": "Exame final", "nota_conselho": "Nota de conselho",
                 "media_final": "Média final"}


def carregar_anterior(origem: str) -> dict | None:
    if not origem:
        return None
    try:
        if origem.startswith("http"):
            url = origem.rstrip("/")
            if not url.endswith(".json"):
                url += "/data.json"
            req = urllib.request.Request(url, headers={"User-Agent": "faltas-univap-bot"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        return json.loads(Path(origem).read_text(encoding="utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(f"Sem versão anterior ({origem}): {e}", file=sys.stderr)
        return None


def valores(d: dict) -> dict:
    """Achata uma disciplina em {campo: valor} só com o que interessa comparar."""
    v = {"faltas": d.get("faltas")}
    notas = d.get("notas") or {}
    for b, bim in enumerate(notas.get("bimestres") or [], start=1):
        for c in COMPONENTES:
            v[f"{c}{b}"] = bim.get(c)
    for campo in CAMPOS_FINAIS:
        v[campo] = notas.get(campo)
    return v


def vazio(x) -> bool:
    # O portal devolve MB = 0 em bimestre não iniciado; não é "nota nova".
    return x is None or x == 0


def comparar(antes: dict, depois: dict, hoje: str) -> list[dict]:
    anteriores = {d["codigo"]: valores(d) for d in antes.get("disciplinas", [])}
    novas = []
    for d in depois.get("disciplinas", []):
        velho = anteriores.get(d["codigo"])
        if velho is None:
            continue
        for campo, valor in valores(d).items():
            ant = velho.get(campo)
            if ant == valor or (vazio(ant) and vazio(valor)):
                continue
            novas.append({"codigo": d["codigo"], "campo": campo,
                          "antes": ant, "depois": valor, "em": hoje})
    return novas


def mesclar(novas: list[dict], antigas: list[dict], hoje: str) -> list[dict]:
    """Junta as mudanças de hoje com as recentes; a de hoje vence se o mesmo
    campo mudou de novo (mantendo o valor de antes mais antigo)."""
    limite = (date.fromisoformat(hoje) - timedelta(days=DIAS_NOVIDADE)).isoformat()
    por_chave = {(m["codigo"], m["campo"]): m for m in antigas if m.get("em", "") > limite}
    for m in novas:
        chave = (m["codigo"], m["campo"])
        if chave in por_chave:
            m = {**m, "antes": por_chave[chave]["antes"]}
        por_chave[chave] = m
    # Some se o valor voltou ao que era (ex.: correção lançada e desfeita).
    return [m for m in por_chave.values() if m["antes"] != m["depois"]]


def fmt(x) -> str:
    if x is None:
        return "—"
    return f"{x:g}".replace(".", ",")


def nome_curto(disciplina: str) -> str:
    partes = disciplina.split(" - ", 1)
    return partes[1] if len(partes) > 1 else disciplina


def rotulo(campo: str) -> str:
    if campo in CAMPOS_FINAIS:
        return CAMPOS_FINAIS[campo]
    comp, bim = campo[:-1], campo[-1]
    return f"{NOME_COMP.get(comp, comp.upper())} {bim}º bim"


def texto_aviso(novas: list[dict], data: dict) -> str:
    por_codigo = {d["codigo"]: d for d in data.get("disciplinas", [])}
    linhas = []
    for codigo in dict.fromkeys(m["codigo"] for m in novas):
        d = por_codigo[codigo]
        partes = []
        for m in (m for m in novas if m["codigo"] == codigo):
            if m["campo"] == "faltas":
                dif = (m["depois"] or 0) - (m["antes"] or 0)
                partes.append(f"{'+' if dif > 0 else ''}{fmt(dif)} falta{'s' if abs(dif) != 1 else ''} "
                              f"(total {fmt(m['depois'])}, ainda pode {fmt(d.get('pode_faltar_ainda'))})")
            else:
                partes.append(f"{rotulo(m['campo'])}: {fmt(m['antes'])} → {fmt(m['depois'])}")
        linhas.append(f"{nome_curto(d['disciplina'])} — " + "; ".join(partes))
    return "\n".join(linhas)


def avisar(topico: str, novas: list[dict], data: dict, url: str) -> None:
    n_notas = sum(m["campo"] != "faltas" for m in novas)
    n_faltas = len(novas) - n_notas
    partes = []
    if n_notas:
        partes.append(f"{n_notas} nota{'s' if n_notas != 1 else ''}")
    if n_faltas:
        partes.append(f"{n_faltas} falta{'s' if n_faltas != 1 else ''}")
    corpo = {
        "topic": topico,
        "title": "Painel UNIVAP: " + " e ".join(partes) + " nova" + ("s" if len(novas) != 1 else ""),
        "message": texto_aviso(novas, data),
        "tags": ["books"],
    }
    if url:
        corpo["click"] = url
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        print("Aviso enviado pelo ntfy.")
    except urllib.error.URLError as e:
        # O painel é o principal; aviso falhar não pode derrubar o deploy.
        print(f"Falha ao enviar aviso pelo ntfy: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default=str(DATA_PATH), help="data.json novo (é reescrito)")
    ap.add_argument("--anterior", default=os.environ.get("PAINEL_URL", ""),
                    help="URL do painel publicado ou caminho de um data.json antigo")
    ap.add_argument("--sem-aviso", action="store_true", help="não manda push, só anota")
    args = ap.parse_args()

    caminho = Path(args.data)
    data = json.loads(caminho.read_text(encoding="utf-8"))
    anterior = carregar_anterior(args.anterior)
    hoje = datetime.now(BRASILIA).date().isoformat()

    novas = comparar(anterior, data, hoje) if anterior else []
    data["mudancas"] = mesclar(novas, (anterior or {}).get("mudancas", []), hoje)
    caminho.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if novas:
        print(f"{len(novas)} mudança(s) nova(s):\n" + texto_aviso(novas, data))
    else:
        print("Nada novo desde a última versão publicada.")
    print(f"{len(data['mudancas'])} mudança(s) recente(s) marcadas no painel.")

    topico = os.environ.get("NTFY_TOPIC", "").strip()
    if novas and topico and not args.sem_aviso:
        url = args.anterior if args.anterior.startswith("http") else ""
        avisar(topico, novas, data, url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
