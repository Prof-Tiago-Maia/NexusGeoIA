"""Smoke test dos artefatos finais do NexusGeo IA.

Valida, sem abrir janela nem servidor, o que o build deixa em ``dist``:

1. os tres artefatos existem e com assinatura valida (``MZ`` para PE,
   ``PK`` para ``.zip``): o pacote ``--onedir``
   (``dist\\NexusGeoIA\\NexusGeoIA.exe`` + ``dist\\NexusGeoIA\\_internal``),
   o pacote portatil e o instalador;
2. o ``.zip`` portatil preserva a pasta raiz, carrega ``NexusGeoIA.exe``
   e ``_internal/`` e nao traz estado local nem segredos (``.dsh``,
   ``.git``, ``.ruff_cache``, ``.pytest_cache``, ``__pycache__``,
   ``tests``, ``.venv``, ``.env*``, ``secrets.toml``,
   ``config_local.json``, ``estrutura.txt``, ``tmp*/``);
3. a pasta de staging, quando ainda existe, tem as mesmas garantias;
4. o executavel passa no autoteste interno (``--autoteste``), que importa
   os modulos criticos e gera um ``.docx`` e um ``.xlsx`` de verdade, e
   na verificacao de imports congelados (``--verificar-imports``), que
   roda com um ``PATH`` sem ``.venv`` e importa ``app`` e
   ``services.llm_service`` de dentro de ``_internal`` - **somente com
   ``--com-executavel``**, porque o aplicativo e desktop (sobe o
   Streamlit e nao termina sozinho) e executar o binario depende da
   politica de execucao da maquina.

Uso:

    .venv\\Scripts\\python.exe packaging\\smoke_test_artefatos.py
    .venv\\Scripts\\python.exe packaging\\smoke_test_artefatos.py --com-executavel

Codigo de saida: 0 quando tudo passa, 1 quando qualquer verificacao
reprova. As mensagens de console ficam em ASCII para nao depender da
code page do Windows (o console do PowerShell usa cp1252 e acentuacao
saira trocada).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Mesmo nome de versao lido de config.py; o build deriva os artefatos dele.
PASTA_STAGING = "NexusGeoIA_v{versao}_Portatil"
ARQUIVO_ZIP = "NexusGeoIA_v{versao}_Portatil.zip"
ARQUIVO_SETUP = "NexusGeoIA_v{versao}_Setup.exe"

# Saida do PyInstaller no modo --onedir: a pasta do aplicativo com o
# carregador e a _internal (sys._MEIPASS) ao lado.
PASTA_ONEDIR = "NexusGeoIA"
ARQUIVO_EXE = "NexusGeoIA.exe"
PASTA_INTERNA = "_internal"

# Entradas que nunca podem viajar para a maquina de destino.
PADROES_PROIBIDOS = (
    "(^|/)(\\.dsh|\\.git|\\.ruff_cache|\\.pytest_cache|__pycache__|tests|\\.venv)(/|$)",
    "(^|/)\\.env(\\.|$|/)",
    "(^|/)(estrutura\\.txt|config_local\\.json|secrets\\.toml)$",
    "(^|/)tmp[^/]*/",
)

# Tamanho minimo para considerar um artefato "de verdade": o bundle
# passa de 100 MB; qualquer coisa muito menor indica build truncado.
TAMANHO_MINIMO_MB = 50.0


def versao_do_config():
    """Le ``APP_VERSION`` de ``config.py`` (fonte unica da verdade)."""

    import re

    conteudo = (RAIZ / "config.py").read_text(encoding="utf-8")
    encontrado = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', conteudo)

    if not encontrado:
        raise RuntimeError("APP_VERSION nao encontrado em config.py")

    return encontrado.group(1)


def _assinatura(caminho, tamanho=2):
    with Path(caminho).open("rb") as arquivo:
        return arquivo.read(tamanho)


def _checar_pe(caminho, rotulo, falhas, tamanho_minimo_mb=TAMANHO_MINIMO_MB):
    """Confirma que o arquivo e um PE (``MZ``) com tamanho plausivel.

    No modo ``--onedir`` o ``NexusGeoIA.exe`` e apenas o carregador
    (poucos MB); o volume do aplicativo fica em ``_internal``. Por isso
    o limite minimo de tamanho e aplicado ao conjunto do pacote, nao ao
    carregador.
    """

    if not caminho.is_file():
        falhas.append(f"{rotulo} ausente: {caminho}")
        return None

    tamanho_mb = round(caminho.stat().st_size / (1024 * 1024), 1)

    if tamanho_mb < tamanho_minimo_mb:
        falhas.append(
            f"{rotulo} pequeno demais ({tamanho_mb} MB < {tamanho_minimo_mb} MB): "
            "build possivelmente truncado"
        )

    if _assinatura(caminho) != b"MZ":
        falhas.append(f"{rotulo} sem assinatura MZ: {caminho}")

    return tamanho_mb


def verificar_pacote_onedir(pacote, falhas):
    """Valida ``dist\\NexusGeoIA``: carregador + ``_internal`` completo."""

    if not pacote.is_dir():
        falhas.append(f"pacote onedir ausente: {pacote}")
        return None

    exe = pacote / ARQUIVO_EXE
    interna = pacote / PASTA_INTERNA

    mb_exe = _checar_pe(
        exe,
        "executavel onedir",
        falhas,
        tamanho_minimo_mb=0,
    )

    if not interna.is_dir():
        falhas.append(f"pasta {PASTA_INTERNA} ausente: {interna}")
        return {"exe_mb": mb_exe, "internal_mb": None}

    # Recursos lidos por caminho: no PyInstaller 6 o sys._MEIPASS do
    # --onedir aponta para _internal.
    for relativo in (
        "app.py",
        "prompts/system_base.txt",
        ".streamlit/config.toml",
        # Bug corrigido: sem o cacert.pem em _internal/certifi o import
        # de services.llm_service (ollama -> httpx -> ssl) quebra com
        # FileNotFoundError antes de a interface abrir.
        "certifi/cacert.pem",
    ):
        if not (interna / relativo).is_file():
            falhas.append(
                f"recurso ausente em {PASTA_INTERNA}: {interna / relativo}"
            )

    mb_interna = round(
        sum(arquivo.stat().st_size for arquivo in interna.rglob("*") if arquivo.is_file())
        / (1024 * 1024),
        1,
    )

    if mb_interna < TAMANHO_MINIMO_MB:
        falhas.append(
            f"pacote onedir pequeno demais ({mb_interna} MB < "
            f"{TAMANHO_MINIMO_MB} MB): build possivelmente truncado"
        )

    return {"exe_mb": mb_exe, "internal_mb": mb_interna}


def _entradas_proibidas(nomes):
    """Devolve as entradas que casam com qualquer padrao proibido."""

    import re

    proibidas = []

    for nome in nomes:
        for padrao in PADROES_PROIBIDOS:
            if re.search(padrao, nome):
                proibidas.append(nome)
                break

    return proibidas


def verificar_zip(caminho, staging, falhas, avisos):
    """Valida assinatura, pasta raiz e conteudo do ``.zip`` portatil."""

    if not caminho.is_file():
        falhas.append(f"pacote portatil ausente: {caminho}")
        return None

    if _assinatura(caminho, 4) != b"PK\x03\x04":
        falhas.append(f"pacote portatil sem assinatura PK: {caminho}")

        return None

    try:
        with zipfile.ZipFile(caminho) as arquivo:
            nomes = arquivo.namelist()
    except zipfile.BadZipFile as erro:
        falhas.append(f"pacote portatil corrompido: {erro}")

        return None

    raiz = staging.name + "/"

    if not any(nome.startswith(raiz) for nome in nomes):
        falhas.append(
            f"o .zip nao preserva a pasta raiz {raiz}; a extracao ficaria solta"
        )

    proibidas = _entradas_proibidas(nomes)

    if proibidas:
        falhas.append(
            f"o .zip contem {len(proibidas)} entrada(s) proibida(s), "
            f"por exemplo: {proibidas[0]}"
        )

    # O pacote --onedir precisa viajar inteiro: o carregador, iniciar.bat
    # e a pasta _internal (sem ela o .exe nao abre).
    for obrigatorio in (ARQUIVO_EXE, "iniciar.bat", "LEIA-ME.txt"):
        if not any(nome == raiz + obrigatorio for nome in nomes):
            falhas.append(f"o .zip nao contem {raiz}{obrigatorio}")

    if not any(nome.startswith(raiz + PASTA_INTERNA + "/") for nome in nomes):
        falhas.append(
            f"o .zip nao contem a pasta {raiz}{PASTA_INTERNA}/; "
            "o executavel nao abriria"
        )

    return {
        "entradas": len(nomes),
        "mb": round(caminho.stat().st_size / (1024 * 1024), 1),
    }


def verificar_staging(staging, falhas, avisos):
    """Aplica as mesmas garantias a pasta de staging, se ela existir."""

    if not staging.is_dir():
        avisos.append(f"pasta de staging ausente (normal com -Limpar): {staging}")

        return None

    nomes = [
        str(arquivo.relative_to(staging)).replace(os.sep, "/")
        for arquivo in staging.rglob("*")
        if arquivo.is_file()
    ]

    proibidas = _entradas_proibidas(nomes)

    if proibidas:
        falhas.append(
            f"a pasta portatil contem {len(proibidas)} arquivo(s) proibido(s), "
            f"por exemplo: {proibidas[0]}"
        )

    return {"arquivos": len(nomes)}


def _ambiente_sem_venv(base=None):
    """Copia o ambiente removendo qualquer caminho do ``.venv``.

    O executável precisa resolver ``app``/``services.llm_service`` de
    dentro de ``_internal``, e não do ambiente virtual usado no build.
    Remover ``.venv``/``site-packages`` do ``PATH`` e as variáveis
    ``PYTHON*`` torna o teste uma prova real do bundle.
    """

    ambiente = dict(os.environ if base is None else base)

    partes = []

    for parte in ambiente.get("PATH", "").split(os.pathsep):
        if not parte.strip():
            continue

        normalizada = parte.replace("\\", "/").lower()

        if ".venv" in normalizada or "site-packages" in normalizada:
            continue

        partes.append(parte)

    ambiente["PATH"] = os.pathsep.join(partes)

    for chave in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
    ):
        ambiente.pop(chave, None)

    return ambiente


def verificar_imports_congelados(exe, raiz, falhas, avisos, timeout=600):
    """Importa ``app``/``services.llm_service`` dentro do executável.

    Roda ``NexusGeoIA.exe --verificar-imports`` (sem GUI, sem servidor e
    sem navegador) com um ``PATH`` sem ``.venv``. O modo valida o
    ``certifi/cacert.pem``, cria um contexto SSL do ``httpx`` e importa a
    cadeia que quebrou na validação real.
    """

    if not exe.is_file():
        falhas.append(f"executavel ausente: {exe}")

        return None

    pasta_relatorio = raiz / "build" / "smoke_artefatos"
    pasta_relatorio.mkdir(parents=True, exist_ok=True)

    relatorio = pasta_relatorio / "imports.json"

    if relatorio.is_file():
        relatorio.unlink()

    ambiente = _ambiente_sem_venv()
    ambiente["ASSISTENTE_IMPORTS_REPORT"] = str(relatorio)
    ambiente["ASSISTENTE_DATA_DIR"] = str(pasta_relatorio / "dados_imports")

    try:
        processo = subprocess.run(
            [str(exe), "--verificar-imports"],
            env=ambiente,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        falhas.append(
            f"a verificacao de imports excedeu {timeout}s "
            "(possivel travamento no import do bundle)"
        )

        return None

    if not relatorio.is_file():
        falhas.append(
            "o executavel nao gravou o relatorio de imports "
            f"(codigo {processo.returncode})"
        )

        return None

    dados = json.loads(relatorio.read_text(encoding="utf-8"))

    if not dados.get("ok"):
        falhas.append(f"imports do bundle reprovados: {dados.get('falhas')}")

    nomes = [
        verificacao.get("nome")
        for verificacao in dados.get("verificacoes", [])
        if verificacao.get("ok")
    ]

    for obrigatorio in ("certificados", "services_llm_service", "app"):
        if obrigatorio not in nomes:
            falhas.append(
                f"verificacao ausente no bundle: {obrigatorio}"
            )

    if dados.get("congelado") is not True:
        avisos.append(
            "o relatorio de imports nao indica modo congelado; "
            "confirme que o .exe foi executado"
        )

    if ".venv" in dados.get("ssl_cert_file", "").replace("\\", "/").lower():
        falhas.append(
            "o bundle usou o cacert.pem do .venv em vez do _internal"
        )

    return {
        "ok": bool(dados.get("ok")),
        "verificacoes": nomes,
        "certificado": dados.get("ssl_cert_file"),
    }


def verificar_executavel(exe, raiz, falhas, avisos, timeout=600):
    """Roda o autoteste embutido no executavel e le o relatorio JSON."""

    if not exe.is_file():
        falhas.append(f"executavel ausente: {exe}")

        return None

    pasta_relatorio = raiz / "build" / "smoke_artefatos"
    pasta_relatorio.mkdir(parents=True, exist_ok=True)

    relatorio = pasta_relatorio / "relatorio.json"

    if relatorio.is_file():
        relatorio.unlink()

    ambiente = dict(os.environ)
    ambiente["ASSISTENTE_SMOKE_REPORT"] = str(relatorio)
    # Pasta de dados isolada: o smoke test nao escreve no perfil do usuario.
    ambiente["ASSISTENTE_DATA_DIR"] = str(pasta_relatorio / "dados")

    try:
        processo = subprocess.run(  # noqa: PLW1510 - o codigo e conferido abaixo
            [str(exe), "--autoteste"],
            env=ambiente,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        falhas.append(
            f"o autoteste do executavel excedeu {timeout}s "
            "(o .exe pode ter travado na extracao do bundle)"
        )

        return None

    if processo.returncode != 0:
        falhas.append(
            f"o autoteste do executavel reprovou (codigo {processo.returncode})"
        )

    if not relatorio.is_file():
        falhas.append("o autoteste nao gravou o relatorio JSON")

        return None

    dados = json.loads(relatorio.read_text(encoding="utf-8"))

    if not dados.get("ok"):
        falhas.append(f"relatorio do autoteste reprovado: {dados.get('falhas')}")

    if dados.get("congelado") is not True:
        avisos.append(
            "o relatorio nao indica modo congelado; "
            "confirme que o .exe foi executado (nao o script)"
        )

    return {
        "ok": bool(dados.get("ok")),
        "congelado": bool(dados.get("congelado")),
        "verificacoes": [
            verificacao.get("nome")
            for verificacao in dados.get("verificacoes", [])
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke test dos artefatos finais do NexusGeo IA.",
    )
    parser.add_argument(
        "--dist",
        default=str(RAIZ / "dist"),
        help="pasta que contem os artefatos (padrao: dist).",
    )
    parser.add_argument(
        "--com-executavel",
        action="store_true",
        help=(
            "executa o .exe com --autoteste (opt-in: o aplicativo e "
            "desktop e nao termina sozinho)"
        ),
    )

    argumentos = parser.parse_args(argv)

    dist = Path(argumentos.dist).resolve()
    versao = versao_do_config()

    staging = dist / PASTA_STAGING.format(versao=versao)
    zip_final = dist / ARQUIVO_ZIP.format(versao=versao)
    pacote = dist / PASTA_ONEDIR
    exe = pacote / ARQUIVO_EXE
    setup = dist / ARQUIVO_SETUP.format(versao=versao)

    falhas = []
    avisos = []
    relatorio = {"versao": versao, "dist": str(dist)}

    print(f"Smoke test dos artefatos do NexusGeo IA v{versao}")
    print(f"  dist: {dist}")

    if not dist.is_dir():
        print(f"FALHA: pasta dist inexistente: {dist}")

        return 1

    print("  [1/4] pacote onedir (NexusGeoIA.exe + _internal)")
    relatorio["executavel"] = verificar_pacote_onedir(pacote, falhas)

    print("  [2/4] pacote portatil (.zip)")
    relatorio["zip"] = verificar_zip(zip_final, staging, falhas, avisos)

    print("  [3/4] pasta de staging")
    relatorio["staging"] = verificar_staging(staging, falhas, avisos)

    print("  [4/4] instalador")
    relatorio["instalador"] = {
        "mb": _checar_pe(setup, "instalador", falhas),
    }

    if argumentos.com_executavel:
        print("  [extra] autoteste do executavel (--autoteste)")
        relatorio["autoteste"] = verificar_executavel(
            exe, RAIZ, falhas, avisos
        )

        print("  [extra] imports congelados (--verificar-imports, sem .venv)")
        relatorio["imports_congelados"] = verificar_imports_congelados(
            exe, RAIZ, falhas, avisos
        )
    else:
        print("  [extra] autoteste do executavel: ignorado (--com-executavel)")

        avisos.append(
            "o .exe nao foi executado; use --com-executavel para validar "
            "os imports dentro do bundle"
        )

    relatorio["falhas"] = falhas
    relatorio["avisos"] = avisos

    pasta_relatorio = RAIZ / "build" / "smoke_artefatos"
    pasta_relatorio.mkdir(parents=True, exist_ok=True)
    destino = pasta_relatorio / "resumo.json"
    destino.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"  Relatorio: {destino}")

    for aviso in avisos:
        print(f"  AVISO: {aviso}")

    if falhas:
        print()
        for falha in falhas:
            print(f"  FALHA: {falha}")
        print()
        print("Smoke test REPROVADO.")

        return 1

    print()
    print("Smoke test APROVADO.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
