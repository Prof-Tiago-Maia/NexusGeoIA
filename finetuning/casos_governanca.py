"""Casos da tarefa de rotulagem e veredito de governança.

Os contratos são apenas entradas: o gabarito (classificações e veredito)
é calculado por core.governance.avaliar_governanca. Há casos válidos,
ambíguos (evidência ausente ou fora do catálogo), incompletos (contrato
sem claims, resposta vazia) e negativos (classificação inválida, texto
livre, falha de fonte e tentativa de declarar PASS sem autoridade).
"""

from __future__ import annotations

OMITIR = object()


def _claim(texto_pt, texto_en, classificacao=OMITIR, evidence_id=OMITIR):
    """Monta uma afirmação bilíngue para o contrato de governança."""

    item = {"texto": (texto_pt, texto_en)}

    if classificacao is not OMITIR:
        item["classificacao"] = classificacao

    if evidence_id is not OMITIR:
        item["evidence_id"] = evidence_id

    return item


def casos_governanca():
    """Devolve os casos de governança (contrato + evidências + família)."""

    resposta = (
        "O teor de ouro é 2,1 g/t no intervalo amostrado.",
        "The gold grade is 2.1 g/t in the sampled interval.",
    )
    return [
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "OBSERVED",
                    "ev_1",
                ),
                _claim(
                    "Pode haver continuidade em profundidade.",
                    "There may be continuity at depth.",
                    "INFERRED",
                ),
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "OBSERVED",
                    "ev_2",
                )
            ],
            "evidencias": ["ev_2"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "observado",
                    "ev_1",
                ),
                _claim(
                    "A falha principal controla a mineralização.",
                    "The main fault controls the mineralization.",
                    "inferência",
                ),
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    evidence_id="ev_1",
                ),
                _claim(
                    "A falha principal controla a mineralização.",
                    "The main fault controls the mineralization.",
                ),
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "HOLD",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "FAIL",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t no intervalo amostrado.",
                    "The gold grade is 2.1 g/t in the sampled interval.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "cerca": True,
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                (
                    "A área apresenta granito.",
                    "The area contains granite.",
                )
            ],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "normal",
            "resposta": (
                "A área apresenta granito e a falha corta o contato.",
                "The area contains granite and the fault cuts the contact.",
            ),
            "claims": [
                _claim(
                    "A área apresenta granito.",
                    "The area contains granite.",
                    "OBSERVED",
                    "ev_a",
                ),
                _claim(
                    "A falha corta o contato.",
                    "The fault cuts the contact.",
                    "OBSERVED",
                    "ev_b",
                ),
            ],
            "veredito": "PASS",
            "evidencias": ["ev_a", "ev_b"],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                )
            ],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_fantasma",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "talvez",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    evidence_id="ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                ),
                _claim(
                    "A falha corta o contato.",
                    "The fault cuts the contact.",
                    "OBSERVED",
                    "ev_fantasma",
                ),
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "incompleto",
            "resposta": resposta,
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "incompleto",
            "resposta": resposta,
            "claims": "não é uma lista",
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "incompleto",
            "resposta": resposta,
            "claims": [{"texto": "", "classificacao": "INFERRED"}],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "incompleto",
            "resposta": ("", ""),
            "claims": [],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "incompleto",
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "incompleto",
            "resposta": resposta,
            "claims": None,
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "TALVEZ",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "negativo",
            "contrato_texto": (
                "Resposta em texto livre, sem contrato de governança.",
                "Free-text answer without a governance contract.",
            ),
            "evidencias": [],
        },
        {
            "familia": "negativo",
            "contrato_texto": ("", ""),
            "evidencias": [],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "falha_fonte": "timeout",
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "falha_fonte": "tls",
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "falha_fonte": "http_503",
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                )
            ],
            "veredito": "PASS",
            "evidencias": [],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "falha_fonte": "rede",
        },
        # ------------------------------------------------------------------
        # Casos v2: vies otimista e coerencia da lista de classificacoes.
        # Cobrem INFERRED com evidencia valida/desconhecida, claim sem
        # texto, classificacao nula, resposta vazia com claims, veredito
        # invalido combinado com classificacao invalida, fonte
        # desconhecida, falha de fonte em texto livre, contrato em lista,
        # aliases do contrato e FAIL declarado sem claims.
        # ------------------------------------------------------------------
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "INFERRED",
                    "ev_1",
                )
            ],
            "evidencias": ["ev_1"],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "INFERRED",
                    "ev_9",
                )
            ],
            "evidencias": ["ev_1"],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "evidencias": [],
        },
        {
            "familia": "incompleto",
            "resposta": resposta,
            "claims": [{"classificacao": "OBSERVED"}],
            "evidencias": [],
        },
        {
            "familia": "ambiguo",
            "resposta": resposta,
            "claims": [
                {
                    "texto": (
                        "O teor de ouro é 2,1 g/t.",
                        "The gold grade is 2.1 g/t.",
                    ),
                    "classificacao": None,
                }
            ],
            "evidencias": [],
        },
        {
            "familia": "normal",
            "resposta": resposta,
            "claims": [],
            "evidencias": [],
        },
        {
            "familia": "negativo",
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "talvez",
                    "ev_1",
                )
            ],
            "veredito": "TALVEZ",
            "evidencias": ["ev_1"],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [
                _claim(
                    "O teor de ouro é 2,1 g/t.",
                    "The gold grade is 2.1 g/t.",
                    "OBSERVED",
                    "ev_1",
                )
            ],
            "veredito": "PASS",
            "evidencias": ["ev_1"],
            "falha_fonte": "dns",
        },
        {
            "familia": "negativo",
            "contrato_texto": (
                "Resposta em texto livre, sem contrato de governança.",
                "Free-text answer without a governance contract.",
            ),
            "evidencias": [],
            "falha_fonte": "timeout",
        },
        {
            "familia": "incompleto",
            "contrato_texto": ("[1, 2, 3]", "[1, 2, 3]"),
            "evidencias": [],
        },
        {
            "familia": "normal",
            "contrato_texto": (
                '{"resposta": "O teor de ouro é 2,1 g/t.", '
                + '"afirmacoes": [{"texto": "O teor de ouro é 2,1 g/t.", '
                + '"classificacao": "OBSERVED", "evidence_id": "ev_1"}], '
                + '"verdict": "PASS"}',
                '{"resposta": "The gold grade is 2.1 g/t.", '
                + '"afirmacoes": [{"texto": "The gold grade is 2.1 g/t.", '
                + '"classificacao": "OBSERVED", "evidence_id": "ev_1"}], '
                + '"verdict": "PASS"}',
            ),
            "evidencias": ["ev_1"],
        },
        {
            "familia": "negativo",
            "resposta": resposta,
            "claims": [],
            "veredito": "FAIL",
            "evidencias": [],
        },
    ]
