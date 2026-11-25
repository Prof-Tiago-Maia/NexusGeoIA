"""Resolução espacial e pacote offline por folha CIM (Fase D2).

Este adaptador é a porta de entrada única para três perguntas da Aba 2:

1. **Onde estou?** Normaliza um par latitude/longitude, detecta inversão
   indevida de eixos e devolve a posição em graus decimais;
2. **Qual é a folha?** Calcula a hierarquia cartográfica completa, de
   ``1:1.000.000`` até ``1:25.000`, a partir de coordenadas ou de um
   código CIM já digitado;
3. **A folha está disponível offline?** Consulta o pacote persistido na
   memória operacional SQLite (``spatial_cache``) e permite consultar e
   exportar os registros sem rede.

O módulo não acessa a internet, não abre a interface e não depende de
Streamlit. A conversão geométrica continua em
``services.spatial_parser``; aqui ficam a validação de entrada, a
hierarquia de escalas e a montagem do manifesto do pacote.

Convenções importantes:

* A latitude vem primeiro e a longitude depois, como nas APIs públicas e
  no restante do projeto;
* um par sem rótulo pode ser invertido **somente** quando a leitura
  direta é geograficamente inválida (por exemplo, latitude 120);
* um par rotulado (``Lat:``/``Lon:``) nunca é invertido para "fazer
  caber": isso transformaria um erro de entrada em um ponto falso.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timezone

from services import db_service
from services.spatial_parser import (
    codigo_folha_cim,
    coordenada_valida,
    decodificar_folha_cim,
)

# Escalas cobertas pela articulação sistemática usada no Brasil.
ESCALAS_CIM = (
    "1:1.000.000",
    "1:500.000",
    "1:250.000",
    "1:100.000",
    "1:50.000",
    "1:25.000",
)

# Rótulos dos quadrantes em cada nível, na ordem linha/coluna (Norte para
# o Sul, Oeste para Leste). Os níveis de 1:100.000 em diante usam a
# numeração oficial da articulação.
_ROTULOS_NIVEIS = (
    ("VXY Z".replace(" ", ""), (("V", "X"), ("Y", "Z"))),
    ("ABCD", (("A", "B"), ("C", "D"))),
    ("I..VI", (("I", "II", "III"), ("IV", "V", "VI"))),
    ("1..4", (("1", "2"), ("3", "4"))),
    ("1..4 (25k)", (("1", "2"), ("3", "4"))),
)

_NUMERO = re.compile(r"[-+]?\d+(?:[.,]\d+)?")

# Erros estáveis consumidos pela interface e pelos testes. Textos
# visíveis ficam em utils/i18n.py; aqui só os códigos.
ERRO_COORDENADA_AUSENTE = "coordenada_ausente"
ERRO_COORDENADA_INVALIDA = "coordenada_invalida"
ERRO_INVERSAO_INDEVIDA = "inversao_indevida"
ERRO_FOLHA_INVALIDA = "folha_cim_invalida"
ERRO_FOLHA_OBRIGATORIA = "folha_cim_obrigatoria"
ERRO_PACOTE_SEM_DADOS = "pacote_sem_dados"


def _numero(valor):
    """Converte número, string com vírgula ou texto solto em float."""

    if isinstance(valor, bool) or valor is None:
        return None

    if isinstance(valor, (int, float)):
        numero = float(valor)
        return numero if math.isfinite(numero) else None

    texto = str(valor).strip().replace("\u2212", "-")

    if not texto:
        return None

    encontrado = _NUMERO.search(texto.replace(" ", ""))

    if encontrado is None:
        return None

    try:
        numero = float(encontrado.group(0).replace(",", "."))
    except ValueError:
        return None

    return numero if math.isfinite(numero) else None


def _hemisferio_latitude(lat):
    return "N" if lat > 0 else "S"


def _hemisferio_longitude(lon):
    return "E" if lon > 0 else "W"


def _disponibilidade_segura(folha, caminho_db=None):
    """Consulta o pacote sem deixar um banco indisponível quebrar a aba."""

    try:
        return db_service.pacote_offline_disponivel(
            folha, caminho_db=caminho_db
        )
    except sqlite3.Error:
        # Diretório somente leitura, banco ainda não criado ou arquivo
        # bloqueado: a resolução continua válida, apenas sem pacote.
        return False


def _pacotes_da_hierarquia(niveis, caminho_db=None):
    """Folhas da hierarquia que têm pacote offline gravado.

    O pacote pode ter sido baixado em qualquer nível (por exemplo
    ``SA.21-V-B``), não apenas na folha de 1:1.000.000. A varredura
    começa pelo nível mais detalhado, para que ``pacote_folha`` nomeie o
    pacote mais específico disponível.
    """

    encontrados = []

    for nivel in reversed(niveis or []):
        codigo = nivel.get("codigo") if isinstance(nivel, dict) else None

        if codigo and _disponibilidade_segura(codigo, caminho_db=caminho_db):
            encontrados.append(codigo)

    return encontrados


def formatar_coordenadas(lat, lon, casas=6):
    """Representação legível e estável do par normalizado."""

    if not coordenada_valida(lat, lon):
        return ""

    return (
        f"{abs(float(lat)):.{casas}f}° {_hemisferio_latitude(float(lat))}, "
        f"{abs(float(lon)):.{casas}f}° {_hemisferio_longitude(float(lon))}"
    )


def normalizar_coordenadas(lat, lon, rotulado=False):
    """Valida e normaliza um par geográfico.

    Devolve um dicionário com ``ok``, ``lat``, ``lon``,
    ``invertida``, ``ambigua`` e, quando falha, ``erro``. A inversão
    automática só acontece em pares não rotulados cuja leitura direta é
    inválida; pares rotulados são recusados com
    ``ERRO_INVERSAO_INDEVIDA`` para não mascarar erro de entrada.
    """

    latitude = _numero(lat)
    longitude = _numero(lon)

    if latitude is None or longitude is None:
        return {
            "ok": False,
            "erro": ERRO_COORDENADA_AUSENTE,
            "lat": None,
            "lon": None,
            "invertida": False,
            "ambigua": False,
        }

    direta = coordenada_valida(latitude, longitude)
    trocada = coordenada_valida(longitude, latitude)

    if direta:
        return {
            "ok": True,
            "erro": None,
            "lat": round(latitude, 6),
            "lon": round(longitude, 6),
            "invertida": False,
            # Um par válido nos dois sentidos é ambíguo, mas não deve ser
            # corrigido: a ordem declarada (ou a convenção lat, lon) manda.
            "ambigua": bool(trocada),
            "formatado": formatar_coordenadas(latitude, longitude),
            "par": f"{latitude:.6f}, {longitude:.6f}",
        }

    if trocada and not rotulado:
        return {
            "ok": True,
            "erro": None,
            "lat": round(longitude, 6),
            "lon": round(latitude, 6),
            "invertida": True,
            "ambigua": False,
            "formatado": formatar_coordenadas(longitude, latitude),
            "par": f"{longitude:.6f}, {latitude:.6f}",
        }

    return {
        "ok": False,
        "erro": (
            ERRO_INVERSAO_INDEVIDA if trocada else ERRO_COORDENADA_INVALIDA
        ),
        "lat": None,
        "lon": None,
        "invertida": False,
        "ambigua": False,
        "inversao_suspeita": bool(trocada),
        "valor_original": (latitude, longitude),
    }


def folha_contem(folha, lat, lon):
    """Diz se o ponto está dentro dos limites da folha CIM."""

    dados = decodificar_folha_cim(folha)

    if dados is None or not coordenada_valida(lat, lon):
        return False

    return (
        dados["lat_min"] <= float(lat) <= dados["lat_max"]
        and dados["lon_min"] <= float(lon) <= dados["lon_max"]
    )


def _nivel_por_escala(escala):
    """Índice do nível de subdivisão correspondente à escala."""

    try:
        return ESCALAS_CIM.index(escala) - 1
    except ValueError:
        return -1


def hierarquia_cim(codigo=None, lat=None, lon=None):
    """Hierarquia cartográfica de 1:1.000.000 até 1:25.000.

    Aceita um código CIM (e devolve os prefixos até a escala informada)
    ou um par de coordenadas (e devolve todos os níveis até 1:25.000).
    Cada item traz código normalizado, escala, centroide e limites.
    """

    if codigo:
        base = decodificar_folha_cim(codigo)

        if base is None:
            return []

        partes = base["codigo"].split("-")
        niveis = []

        for tamanho in range(1, len(partes) + 1):
            prefixo = "-".join(partes[:tamanho])
            dados = decodificar_folha_cim(prefixo)

            if dados is not None:
                niveis.append(dados)

        return niveis

    if not coordenada_valida(lat, lon):
        return []

    base = decodificar_folha_cim(codigo_folha_cim(lat, lon))

    if base is None:
        return []

    niveis = [base]
    atual = base

    for rotulos, grade in _ROTULOS_NIVEIS:
        centro_lat = atual["lat"]
        centro_lon = atual["lon"]
        linha = 0 if float(lat) >= centro_lat else 1
        coluna = 0 if float(lon) < centro_lon else 1
        rotulo = grade[linha][coluna]
        proximo = decodificar_folha_cim(f"{atual['codigo']}-{rotulo}")

        if proximo is None:
            break

        niveis.append(proximo)
        atual = proximo

    return niveis


def _hierarquia_resumida(niveis):
    """Lista enxuta para a tabela da interface e para o manifesto."""

    return [
        {
            "codigo": nivel["codigo"],
            "escala": nivel["escala"],
            "lat": nivel["lat"],
            "lon": nivel["lon"],
            "lat_min": nivel["lat_min"],
            "lat_max": nivel["lat_max"],
            "lon_min": nivel["lon_min"],
            "lon_max": nivel["lon_max"],
            "limites": nivel["limites"],
        }
        for nivel in niveis
    ]


def resolver_consulta_espacial(
    lat=None,
    lon=None,
    codigo=None,
    rotulado=False,
    caminho_db=None,
):
    """Resolve coordenadas ou código CIM em um resultado único.

    O retorno é sempre um dicionário (nunca levanta exceção por entrada
    inválida) e inclui ``pacote_disponivel``, consultado na memória
    operacional SQLite. A interface usa esse campo para avisar se a folha
    pode ser consultada sem rede.
    """

    if codigo is not None and str(codigo).strip():
        folha = decodificar_folha_cim(str(codigo).strip())

        if folha is None:
            return {
                "ok": False,
                "erro": ERRO_FOLHA_INVALIDA,
                "codigo": str(codigo).strip().upper(),
            }

        niveis = hierarquia_cim(codigo=folha["codigo"])
        base = niveis[0] if niveis else folha
        # O pacote pode existir em qualquer nível da hierarquia
        # (1:1.000.000 até a folha detalhada escolhida).
        pacotes = _pacotes_da_hierarquia(niveis, caminho_db=caminho_db)
        disponivel = bool(pacotes)

        return {
            "ok": True,
            "erro": None,
            "origem": "codigo",
            "codigo": folha["codigo"],
            "escala": folha["escala"],
            "folha_cim": base["codigo"],
            "lat": folha["lat"],
            "lon": folha["lon"],
            "lat_min": folha["lat_min"],
            "lat_max": folha["lat_max"],
            "lon_min": folha["lon_min"],
            "lon_max": folha["lon_max"],
            "limites": folha["limites"],
            "coordenadas": {
                "ok": True,
                "lat": folha["lat"],
                "lon": folha["lon"],
                "invertida": False,
                "ambigua": False,
                "formatado": formatar_coordenadas(
                    folha["lat"], folha["lon"]
                ),
                "par": f"{folha['lat']:.6f}, {folha['lon']:.6f}",
            },
            "hierarquia": _hierarquia_resumida(niveis),
            "pacote_disponivel": disponivel,
            "pacote_folha": pacotes[0] if pacotes else None,
            "pacotes_disponiveis": pacotes,
        }

    normalizado = normalizar_coordenadas(lat, lon, rotulado=rotulado)

    if not normalizado["ok"]:
        return {
            "ok": False,
            "erro": normalizado["erro"],
            "inversao_suspeita": normalizado.get(
                "inversao_suspeita", False
            ),
            "coordenadas": normalizado,
        }

    niveis = hierarquia_cim(
        lat=normalizado["lat"], lon=normalizado["lon"]
    )
    base = niveis[0] if niveis else None
    detalhada = niveis[-1] if niveis else None
    folha_base = base["codigo"] if base else codigo_folha_cim(
        normalizado["lat"], normalizado["lon"]
    )
    # A folha selecionada pode ser a 1:25.000: a disponibilidade
    # considera todos os níveis da hierarquia, não só a base.
    pacotes = _pacotes_da_hierarquia(niveis, caminho_db=caminho_db)
    disponivel = bool(pacotes)

    return {
        "ok": True,
        "erro": None,
        "origem": "coordenada",
        "codigo": detalhada["codigo"] if detalhada else folha_base,
        "escala": detalhada["escala"] if detalhada else "1:1.000.000",
        "folha_cim": folha_base,
        "lat": normalizado["lat"],
        "lon": normalizado["lon"],
        "lat_min": base["lat_min"] if base else None,
        "lat_max": base["lat_max"] if base else None,
        "lon_min": base["lon_min"] if base else None,
        "lon_max": base["lon_max"] if base else None,
        "limites": base["limites"] if base else "",
        "coordenadas": normalizado,
        "hierarquia": _hierarquia_resumida(niveis),
        "pacote_disponivel": disponivel,
        "pacote_folha": pacotes[0] if pacotes else None,
        "pacotes_disponiveis": pacotes,
    }


def _chave_fonte(feicao):
    """Identificador estável da fonte/camada de uma feição."""

    return str(
        feicao.get("fonte")
        or feicao.get("camada")
        or feicao.get("source_type")
        or "documentos"
    ).strip() or "documentos"


def _agrupar_por_fonte(feicoes, folha):
    """Separa as feições da folha por fonte, mantendo a ordem de entrada."""

    grupos = {}

    for feicao in feicoes or []:
        if not isinstance(feicao, dict):
            continue

        lat = _numero(feicao.get("lat"))
        lon = _numero(feicao.get("lon"))

        if not folha_contem(folha, lat, lon):
            continue

        fonte = _chave_fonte(feicao)
        grupos.setdefault(fonte, []).append(dict(feicao))

    return grupos


def montar_pacote_offline(
    folha,
    feicoes=None,
    collected_at=None,
    source_version=None,
):
    """Monta o manifesto e os registros por fonte de uma folha CIM.

    O pacote é deliberadamente simples: o manifesto guarda
    ``cim_code``, ``collected_at``, ``source_version``, os limites e
    os totais por fonte; os registros ficam em ``spatial_cache``, uma
    linha por folha/fonte. Nenhuma chamada de rede é feita.
    """

    dados = decodificar_folha_cim(folha)

    if dados is None:
        return {
            "ok": False,
            "erro": ERRO_FOLHA_INVALIDA,
        }

    momento = collected_at or db_service.agora_iso()
    versao = str(source_version or "").strip() or f"sessao:{momento}"
    grupos = _agrupar_por_fonte(feicoes, dados["codigo"])

    totais = {
        fonte: len(registros) for fonte, registros in grupos.items()
    }
    total = sum(totais.values())

    manifesto = {
        "schema_version": 1,
        "cim_code": dados["codigo"],
        "folha_cim": dados["codigo"],
        "escala": dados["escala"],
        "collected_at": momento,
        "source_version": versao,
        "lat": dados["lat"],
        "lon": dados["lon"],
        "lat_min": dados["lat_min"],
        "lat_max": dados["lat_max"],
        "lon_min": dados["lon_min"],
        "lon_max": dados["lon_max"],
        "limites": dados["limites"],
        "total_registros": total,
        "totais_por_fonte": totais,
        "fontes": [
            {
                "fonte": fonte,
                "total": len(registros),
            }
            for fonte, registros in grupos.items()
        ],
    }

    return {
        "ok": True,
        "erro": None,
        "manifesto": manifesto,
        "fontes": {
            fonte: {
                "total": len(registros),
                "registros": registros,
            }
            for fonte, registros in grupos.items()
        },
    }


def salvar_pacote_offline(
    folha,
    feicoes=None,
    collected_at=None,
    source_version=None,
    caminho_db=None,
):
    """Monta e persiste o pacote, devolvendo o manifesto gravado."""

    pacote = montar_pacote_offline(
        folha,
        feicoes=feicoes,
        collected_at=collected_at,
        source_version=source_version,
    )

    if not pacote["ok"]:
        return pacote

    # Um pacote vazio não pode substituir um snapshot anterior: a
    # atualização de outra folha (ou de uma folha sem feições
    # compatíveis) apagaria o cache offline que o usuário já tinha.
    if int(pacote["manifesto"].get("total_registros") or 0) <= 0:
        return {
            "ok": False,
            "erro": ERRO_PACOTE_SEM_DADOS,
            "manifesto": None,
        }

    # O adaptador pode ser usado por um script isolado (AppTest, CLI):
    # garante o schema operacional antes da primeira gravação. A operação
    # é idempotente e não toca no banco real quando o caminho é explícito.
    db_service.inicializar_banco(caminho_db)

    gravado = db_service.salvar_pacote_offline_cim(
        pacote["manifesto"],
        pacote["fontes"],
        caminho_db=caminho_db,
    )

    return {
        "ok": True,
        "erro": None,
        "manifesto": gravado,
    }


def obter_pacote_offline(folha, caminho_db=None):
    """Lê o pacote persistido (manifesto e contagens) sem usar rede."""

    try:
        return db_service.obter_pacote_offline_cim(
            folha, caminho_db=caminho_db
        )
    except sqlite3.Error:
        return None


def pacote_offline_disponivel(folha, caminho_db=None):
    """Atalho booleano para a verificação de disponibilidade."""

    try:
        return db_service.pacote_offline_disponivel(
            folha, caminho_db=caminho_db
        )
    except sqlite3.Error:
        return False


def consultar_pacote_offline(folha, fonte=None, caminho_db=None):
    """Consulta 100% offline os registros gravados de uma folha.

    Devolve o manifesto, as linhas de ``spatial_cache`` e a lista
    achatada de feições. Quando não há pacote, ``disponivel`` é falso e
    nenhuma exceção é levantada.
    """

    pacote = obter_pacote_offline(folha, caminho_db=caminho_db)

    if not pacote:
        return {
            "disponivel": False,
            "manifesto": None,
            "fontes": [],
            "feicoes": [],
        }

    feicoes = []

    for entrada in pacote.get("fontes") or []:
        if fonte is not None and entrada.get("fonte") != fonte:
            continue

        payload = entrada.get("payload") or {}
        registros = payload.get("registros") if isinstance(payload, dict) else None

        if registros is None and isinstance(payload, list):
            registros = payload

        for registro in registros or []:
            if isinstance(registro, dict):
                item = dict(registro)
                item.setdefault("fonte", entrada.get("fonte"))
                feicoes.append(item)

    return {
        "disponivel": True,
        "manifesto": pacote.get("manifesto"),
        "fontes": pacote.get("fontes") or [],
        "feicoes": feicoes,
    }


def listar_pacotes_offline(caminho_db=None):
    """Lista os pacotes disponíveis, do mais recente para o mais antigo."""

    try:
        return db_service.listar_pacotes_offline_cim(
            caminho_db=caminho_db
        )
    except sqlite3.Error:
        return []


def remover_pacote_offline(folha, caminho_db=None):
    """Remove o manifesto e as linhas de cache da folha."""

    return db_service.remover_pacote_offline_cim(
        folha, caminho_db=caminho_db
    )


def _agora_local():
    """Data/hora local em ISO 8601, usada apenas em diagnósticos."""

    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )
