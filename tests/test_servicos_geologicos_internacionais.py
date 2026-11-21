"""Testes offline dos serviços geológicos internacionais.

Todos os testes usam mocks de rede (ou parsers puros) e um diretório de
cache temporário. Nenhum portal externo é acessado e nenhum navegador é
aberto.
"""

import shutil
import unittest
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import core.assistant as assistant
import core.prompt_manager as prompt_manager
import services.external_api_service as servico
from services.report_generator import gerar_parecer_markdown
from services.spatial_parser import consolidar_pontos_mapa


@contextmanager
def _cache_temporario():
    """Diretório de cache dentro do projeto, limpo ao final do teste."""

    base = Path(__file__).resolve().parent / "_tmp_cache_api"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    try:
        yield base / "cache_api"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _registro(titulo, fonte, link, lat=None, lon=None):
    """Registro mínimo no schema padrão das fontes externas."""

    return {
        "titulo": titulo,
        "autores": "Serviço Geológico de Teste",
        "ano": "2026",
        "resumo": "Registro usado apenas em teste.",
        "link": link,
        "link_pdf": None,
        "fonte": fonte,
        "lat": lat,
        "lon": lon,
    }


class TestOrquestradorInternacional(unittest.TestCase):
    """Catálogo, filtro por região, paralelismo e deduplicação."""

    def test_catalogo_tem_dez_servicos_com_funcoes_validas(self):
        self.assertEqual(len(servico.SERVICOS_GEOLOGICOS_INTERNACIONAIS), 10)
        self.assertEqual(len(servico.OPCOES_REGIOES_INTERNACIONAIS), 11)

        for descricao in servico.SERVICOS_GEOLOGICOS_INTERNACIONAIS:
            funcao = getattr(servico, descricao["funcao"])
            self.assertTrue(callable(funcao))
            self.assertIn(descricao["opcao"], servico.OPCOES_REGIOES_INTERNACIONAIS)

    def _executar_com_fakes(self, regioes, limite_total=16, mesmo_link=False):
        chamadas = []

        def criar_fake(chave):
            def fake(termo, *args, **kwargs):
                chamadas.append((chave, termo, kwargs))
                link = (
                    "https://exemplo.org/mesmo"
                    if mesmo_link
                    else f"https://exemplo.org/{chave}"
                )
                return [_registro(f"Registro {chave}", f"Fonte {chave}", link)]

            return fake

        with _cache_temporario() as cache:
            with patch.object(servico, "CACHE_API_DIR", cache):
                with ExitStack() as pilha:
                    for descricao in servico.SERVICOS_GEOLOGICOS_INTERNACIONAIS:
                        pilha.enter_context(
                            patch.object(
                                servico,
                                descricao["funcao"],
                                side_effect=criar_fake(descricao["chave"]),
                            )
                        )

                    resultado = (
                        servico.consultar_servicos_geologicos_internacionais(
                            "ouro",
                            regioes_selecionadas=regioes,
                            lat=-3.1,
                            lon=-60.0,
                            limite_total=limite_total,
                        )
                    )

        return resultado, chamadas

    def test_todas_as_regioes_dispara_os_dez_conectores(self):
        resultado, chamadas = self._executar_com_fakes(
            [servico.REGIAO_TODAS]
        )

        self.assertEqual(len(chamadas), 10)
        # GeoNet NZ e GSJ Japão devolvem listas fixas e, numa busca
        # global por "ouro" (preparada como "gold"), não têm relação
        # temática: os dois registros genéricos são descartados.
        self.assertEqual(len(resultado), 8)
        self.assertEqual(
            {descricao["chave"] for descricao in servico.SERVICOS_GEOLOGICOS_INTERNACIONAIS},
            {chave for chave, _termo, _kwargs in chamadas},
        )

    def test_lista_vazia_tambem_dispara_todos(self):
        resultado, chamadas = self._executar_com_fakes([])

        self.assertEqual(len(chamadas), 10)
        self.assertEqual(len(resultado), 8)

    def test_filtro_executa_somente_as_regioes_escolhidas(self):
        regioes = [
            servico.OPCOES_REGIOES_INTERNACIONAIS[3],
            servico.OPCOES_REGIOES_INTERNACIONAIS[6],
        ]
        resultado, chamadas = self._executar_com_fakes(regioes)

        self.assertEqual(
            [chave for chave, _termo, _kwargs in chamadas],
            ["canada", "japao"],
        )
        self.assertEqual(
            {registro["fonte"] for registro in resultado},
            {"Fonte canada", "Fonte japao"},
        )

    def test_deduplica_por_link_preservando_a_primeira_origem(self):
        resultado, chamadas = self._executar_com_fakes(
            [
                servico.OPCOES_REGIOES_INTERNACIONAIS[1],
                servico.OPCOES_REGIOES_INTERNACIONAIS[2],
            ],
            mesmo_link=True,
        )

        self.assertEqual(len(chamadas), 2)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["fonte"], "Fonte onegeology")

    def test_limite_total_corta_o_resultado_consolidado(self):
        resultado, _chamadas = self._executar_com_fakes(
            [servico.REGIAO_TODAS],
            limite_total=3,
        )

        self.assertEqual(len(resultado), 3)

    def _executar_com_fabricas(
        self,
        termo,
        fabrica,
        regioes=None,
        limite_total=18,
    ):
        """Executa o orquestrador com um retorno controlado por conector."""

        chamadas = []

        def criar_fake(chave):
            def fake(termo_arg, *args, **kwargs):
                chamadas.append((chave, termo_arg))
                return fabrica(chave, termo_arg)

            return fake

        with _cache_temporario() as cache:
            with patch.object(servico, "CACHE_API_DIR", cache):
                with ExitStack() as pilha:
                    for descricao in servico.SERVICOS_GEOLOGICOS_INTERNACIONAIS:
                        pilha.enter_context(
                            patch.object(
                                servico,
                                descricao["funcao"],
                                side_effect=criar_fake(descricao["chave"]),
                            )
                        )

                    resultado = (
                        servico.consultar_servicos_geologicos_internacionais(
                            termo,
                            regioes_selecionadas=(
                                [servico.REGIAO_TODAS]
                                if regioes is None
                                else regioes
                            ),
                            limite_total=limite_total,
                        )
                    )

        return resultado, chamadas

    def test_busca_global_tematica_descarta_geonet_e_gsj_genericos(self):
        def fabrica(chave, _termo):
            if chave == "japao":
                return [_registro(
                    "Seamless Digital Geological Map of Japan 1:200,000",
                    servico.FONTE_JAPAO,
                    "https://exemplo.org/japao",
                )]

            if chave == "nova_zelandia":
                return [_registro(
                    "Sismo M4.5 — Teste",
                    servico.FONTE_NOVA_ZELANDIA,
                    "https://exemplo.org/nova-zelandia",
                )]

            if chave == "usgs":
                return [_registro(
                    "Komatiite-hosted Ni-Cu-PGE deposits",
                    servico.FONTE_USGS_INTERNACIONAL,
                    "https://exemplo.org/usgs",
                )]

            return []

        resultado, chamadas = self._executar_com_fabricas(
            "ocorrências de komatiitos mineralizados no mundo",
            fabrica,
        )
        fontes = {registro["fonte"] for registro in resultado}

        self.assertNotIn(servico.FONTE_JAPAO, fontes)
        self.assertNotIn(servico.FONTE_NOVA_ZELANDIA, fontes)
        self.assertIn(servico.FONTE_USGS_INTERNACIONAL, fontes)
        # O termo que chega aos conectores é o inglês preparado, nunca a
        # frase inteira em português.
        self.assertTrue(
            all(termo == "komatiite" for _chave, termo in chamadas)
        )

    def test_busca_global_mantem_geonet_quando_o_tema_e_sismico(self):
        def fabrica(chave, _termo):
            if chave == "nova_zelandia":
                return [_registro(
                    "Sismo M4.5 — Teste",
                    servico.FONTE_NOVA_ZELANDIA,
                    "https://exemplo.org/nova-zelandia",
                )]

            return []

        resultado, _chamadas = self._executar_com_fabricas(
            "terremotos recentes na Nova Zelândia",
            fabrica,
        )

        self.assertEqual(
            [registro["fonte"] for registro in resultado],
            [servico.FONTE_NOVA_ZELANDIA],
        )

    def test_busca_global_mantem_gsj_quando_o_tema_e_o_japao(self):
        def fabrica(chave, _termo):
            if chave == "japao":
                return [_registro(
                    "Seamless Digital Geological Map of Japan 1:200,000",
                    servico.FONTE_JAPAO,
                    "https://exemplo.org/japao",
                )]

            return []

        resultado, _chamadas = self._executar_com_fabricas(
            "mapa geológico do Japão",
            fabrica,
        )

        self.assertEqual(
            [registro["fonte"] for registro in resultado],
            [servico.FONTE_JAPAO],
        )

    def test_regiao_explicita_nao_aplica_o_filtro_de_ruido(self):
        def fabrica(chave, _termo):
            if chave == "nova_zelandia":
                return [_registro(
                    "Sismo M4.5 — Teste",
                    servico.FONTE_NOVA_ZELANDIA,
                    "https://exemplo.org/nova-zelandia",
                )]

            return []

        resultado, _chamadas = self._executar_com_fabricas(
            "komatiite",
            fabrica,
            regioes=[servico.OPCOES_REGIOES_INTERNACIONAIS[7]],
        )

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["fonte"], servico.FONTE_NOVA_ZELANDIA)

    def test_distribuicao_balanceada_entre_servicos_relevantes(self):
        def fabrica(chave, _termo):
            return [
                _registro(
                    f"{chave} registro {indice}",
                    f"Fonte {chave}",
                    f"https://exemplo.org/{chave}/{indice}",
                )
                for indice in range(3)
            ]

        resultado, _chamadas = self._executar_com_fabricas(
            "komatiite",
            fabrica,
            limite_total=18,
        )
        contagem = Counter(registro["fonte"] for registro in resultado)

        self.assertEqual(len(resultado), 18)
        self.assertLessEqual(max(contagem.values()), 3)
        # Oito serviços temáticos (sem Japão e Nova Zelândia) devem
        # aparecer, garantindo diversidade geográfica.
        for chave in (
            "onegeology",
            "usgs",
            "canada",
            "egdi",
            "australia",
            "africa",
            "arabia",
            "india",
        ):
            self.assertIn(f"Fonte {chave}", contagem)


class TestPreparacaoQueryGeologica(unittest.TestCase):
    """Preparação PT -> EN dos termos enviados aos catálogos."""

    def test_komatiitos_mineralizados_viram_komatiite(self):
        self.assertEqual(
            servico._preparar_query_geologica_en(
                "ocorrências de komatiitos mineralizados"
            ),
            "komatiite",
        )

    def test_pergunta_global_remove_mundo_e_ocorrencias(self):
        self.assertEqual(
            servico._preparar_query_geologica_en(
                "ocorrências de komatiitos mineralizados no mundo"
            ),
            "komatiite",
        )

    def test_traduz_minerais_craton_e_toponimo(self):
        texto = servico._preparar_query_geologica_en(
            "níquel e cobre no cráton Yilgarn"
        )

        for termo in ("nickel", "copper", "craton", "yilgarn"):
            self.assertIn(termo, texto.split())

        for termo_pt in ("niquel", "cobre"):
            self.assertNotIn(termo_pt, texto.split())

    def test_terras_raras_como_expressao(self):
        self.assertEqual(
            servico._preparar_query_geologica_en("terras raras no mundo"),
            "rare earth",
        )

    def test_kimberlitos_e_lateritas(self):
        self.assertEqual(
            servico._preparar_query_geologica_en("kimberlitos e lateritas"),
            "kimberlite laterite",
        )

    def test_bacia_e_vulcanismo(self):
        self.assertEqual(
            servico._preparar_query_geologica_en("bacia e vulcanismo"),
            "basin volcanism",
        )

    def test_stopwords_em_ingles(self):
        self.assertEqual(
            servico._preparar_query_geologica_en(
                "where what is komatiite"
            ),
            "komatiite",
        )

    def test_pergunta_sem_termo_geologico_fica_vazia(self):
        self.assertEqual(
            servico._preparar_query_geologica_en("o que é isso?"),
            "",
        )


class TestConectoresEParsers(unittest.TestCase):
    """Leitura de CSW, CKAN, GeoJSON e fallback silencioso."""

    def test_parser_csw_extrai_titulo_resumo_bbox_e_fonte(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <csw:GetRecordsResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"
            xmlns:gmd="http://www.isotc211.org/2005/gmd"
            xmlns:gco="http://www.isotc211.org/2005/gco">
          <csw:SearchResults>
            <gmd:MD_Metadata>
              <gmd:fileIdentifier><gco:CharacterString>abc-123</gco:CharacterString></gmd:fileIdentifier>
              <gmd:identificationInfo>
                <gmd:MD_DataIdentification>
                  <gmd:citation><gmd:CI_Citation>
                    <gmd:title><gco:CharacterString>Geological map of test area</gco:CharacterString></gmd:title>
                  </gmd:CI_Citation></gmd:citation>
                  <gmd:abstract><gco:CharacterString>Mapa geológico de teste.</gco:CharacterString></gmd:abstract>
                  <gmd:extent><gmd:EX_Extent><gmd:geographicElement>
                    <gmd:EX_GeographicBoundingBox>
                      <gmd:westBoundLongitude><gco:Decimal>-60.0</gco:Decimal></gmd:westBoundLongitude>
                      <gmd:eastBoundLongitude><gco:Decimal>-59.0</gco:Decimal></gmd:eastBoundLongitude>
                      <gmd:southBoundLatitude><gco:Decimal>-4.0</gco:Decimal></gmd:southBoundLatitude>
                      <gmd:northBoundLatitude><gco:Decimal>-3.0</gco:Decimal></gmd:northBoundLatitude>
                    </gmd:EX_GeographicBoundingBox>
                  </gmd:geographicElement></gmd:EX_Extent></gmd:extent>
                </gmd:MD_DataIdentification>
              </gmd:identificationInfo>
            </gmd:MD_Metadata>
          </csw:SearchResults>
        </csw:GetRecordsResponse>"""

        registros = servico._geo_parse_csw(
            xml,
            servico.FONTE_ONEGEOLOGY,
            4,
        )

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["fonte"], servico.FONTE_ONEGEOLOGY)
        self.assertIn("Geological map", registros[0]["titulo"])
        self.assertEqual(registros[0]["lat"], -3.5)
        self.assertEqual(registros[0]["lon"], -59.5)

    def test_conector_onegeology_usa_parser_e_cache(self):
        xml = """<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"
            xmlns:gco="http://www.isotc211.org/2005/gco">
          <gmd:fileIdentifier><gco:CharacterString>id-1</gco:CharacterString></gmd:fileIdentifier>
          <gmd:identificationInfo><gmd:MD_DataIdentification>
            <gmd:citation><gmd:CI_Citation><gmd:title>
              <gco:CharacterString>OneGeology test</gco:CharacterString>
            </gmd:title></gmd:CI_Citation></gmd:citation>
            <gmd:abstract><gco:CharacterString>Teste de cache.</gco:CharacterString></gmd:abstract>
          </gmd:MD_DataIdentification></gmd:identificationInfo>
        </gmd:MD_Metadata>"""

        with _cache_temporario() as cache:
            with patch.object(servico, "CACHE_API_DIR", cache):
                with patch.object(
                    servico,
                    "_geo_requisitar",
                    return_value=xml,
                ) as requisitar:
                    primeira = servico.consultar_onegeology("gold", limite=4)
                    segunda = servico.consultar_onegeology("gold", limite=4)

        self.assertEqual(len(primeira), 1)
        self.assertEqual(primeira, segunda)
        # A segunda chamada veio do cache: só houve uma requisição HTTP.
        self.assertEqual(requisitar.call_count, 1)

    def test_parser_ckan_extrai_coordenadas_do_spatial(self):
        dados = {
            "success": True,
            "result": {
                "results": [{
                    "title": "Gold in Canada",
                    "notes": "Estudo de ouro.",
                    "name": "gold-canada",
                    "organization": {"title": "Natural Resources Canada"},
                    "date_published": "2024-01-01",
                    "spatial": (
                        '{"type":"Polygon","coordinates":'
                        '[[[-75.0,45.0],[-74.0,45.0],[-74.0,46.0],'
                        '[-75.0,46.0],[-75.0,45.0]]]}'
                    ),
                    "resources": [],
                }]
            },
        }

        registros = servico._geo_parse_ckan(
            dados,
            servico.FONTE_CANADA,
            4,
            "https://open.canada.ca/data/en/dataset",
        )

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["lat"], 45.5)
        self.assertEqual(registros[0]["lon"], -74.5)
        self.assertEqual(registros[0]["fonte"], servico.FONTE_CANADA)

    def test_geonet_retorna_sismo_e_vulcao_com_coordenadas(self):
        terremoto = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [176.0, -40.0]},
                "properties": {
                    "publicID": "2026p1",
                    "time": "2026-11-17T00:00:00Z",
                    "magnitude": 4.5,
                    "locality": "10 km north of Test",
                    "depth": 12,
                    "quality": "best",
                },
            }],
        }
        vulcao = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [175.5, -39.0]},
                "properties": {
                    "volcanoID": "ruapehu",
                    "volcanoTitle": "Ruapehu",
                    "level": 1,
                    "activity": "Minor volcanic unrest.",
                    "hazards": "Volcanic unrest hazards.",
                },
            }],
        }

        def requisitar(url, *args, **kwargs):
            if "quake" in url:
                return terremoto
            if "volcano" in url:
                return vulcao
            return None

        with _cache_temporario() as cache:
            with patch.object(servico, "CACHE_API_DIR", cache):
                with patch.object(
                    servico,
                    "_geo_requisitar",
                    side_effect=requisitar,
                ):
                    registros = servico.consultar_geonet_nz(
                        "terremoto",
                        limite=4,
                    )

        self.assertEqual(len(registros), 2)
        self.assertTrue(all(r["fonte"] == servico.FONTE_NOVA_ZELANDIA for r in registros))
        self.assertTrue(all("lat" in r and "lon" in r for r in registros))

    def test_fallback_silencioso_de_erro_de_rede(self):
        with _cache_temporario() as cache:
            with patch.object(servico, "CACHE_API_DIR", cache):
                with patch.object(
                    servico,
                    "_geo_requisitar",
                    return_value=None,
                ):
                    registros = servico.consultar_canada_nrcan(
                        "gold",
                        limite=4,
                    )

        self.assertEqual(registros, [])

    def test_tabela_identifica_o_servico_de_origem(self):
        tabela = servico.montar_tabela_servicos_geologicos([
            _registro(
                "Gold in Canada",
                servico.FONTE_CANADA,
                "https://exemplo.org/canada",
                45.0,
                -75.0,
            )
        ])

        self.assertIn("Serviço geológico", tabela)
        self.assertIn("NRCan / GSC (Canadá)", tabela)
        self.assertIn("Gold in Canada", tabela)


class TestIntegracaoNoAssistenteEParecer(unittest.TestCase):
    """Assistente, prompt, mapa espacial e referências ABNT."""

    def _resultado_responder(self, pergunta="ouro no Canadá", **kwargs):
        capturado = {}

        def fake_prompt(dados, texto_base=None, pergunta=None):
            capturado["dados"] = dados
            return "PROMPT DE TESTE"

        def fake_gerar(**parametros):
            capturado["prompt_sistema"] = parametros.get(
                "prompt_sistema",
                "",
            )
            return "RESPOSTA DE TESTE"

        with patch.object(
            assistant,
            "decidir_roteamento",
            return_value={
                "intencao": "GERAL",
                "justificativa": "teste",
                "origem": "teste",
                "documentos_locais": [],
            },
        ), patch.object(
            assistant,
            "consultar_servicos_geologicos_internacionais",
            return_value=[_registro(
                "Gold in Canada",
                servico.FONTE_CANADA,
                "https://exemplo.org/canada",
                45.0,
                -75.0,
            )],
        ) as orquestrador, patch.object(
            assistant,
            "montar_prompt_sistema",
            side_effect=fake_prompt,
        ), patch.object(
            assistant,
            "gerar_resposta",
            side_effect=fake_gerar,
        ):
            resultado = assistant.responder(
                pergunta,
                usar_sgb=False,
                usar_documentos=False,
                **kwargs,
            )

        return resultado, capturado, orquestrador

    def test_prompt_traz_sintese_metalogenetica_global(self):
        resultado, capturado, _orquestrador = self._resultado_responder(
            pergunta=(
                "ocorrências de komatiitos mineralizados no mundo"
            ),
            usar_intl_geo=True,
            regioes_intl_geo=[servico.REGIAO_TODAS],
        )
        prompt = capturado["prompt_sistema"]

        self.assertEqual(
            resultado["dados"]["intl_geo"]["limite"],
            18,
        )
        self.assertIn("SÍNTESE METALOGENÉTICA GLOBAL", prompt)
        self.assertIn("Síntese geocientífica de referência", prompt)
        self.assertIn("Kambalda", prompt)
        self.assertIn("Abitibi", prompt)
        self.assertIn("Kaapvaal", prompt)
        self.assertIn("Quadrilátero Ferrífero", prompt)
        self.assertIn("registro recuperado da API", prompt)

    def test_prompt_local_nao_recebe_sintese_global(self):
        _resultado, capturado, _orquestrador = self._resultado_responder(
            pergunta="ouro no Canadá",
            usar_intl_geo=True,
            regioes_intl_geo=[servico.OPCOES_REGIOES_INTERNACIONAIS[3]],
        )

        self.assertNotIn(
            "SÍNTESE METALOGENÉTICA GLOBAL",
            capturado["prompt_sistema"],
        )

    def test_responder_passa_regioes_e_injeta_tabela(self):
        regioes = [servico.OPCOES_REGIOES_INTERNACIONAIS[3]]
        resultado, capturado, orquestrador = self._resultado_responder(
            usar_intl_geo=True,
            regioes_intl_geo=regioes,
        )

        self.assertEqual(
            orquestrador.call_args.kwargs["regioes_selecionadas"],
            regioes,
        )
        self.assertIn("intl_geo", resultado["dados"])
        self.assertIn("intl_geo", capturado["dados"])
        self.assertIn(
            "Serviços Geológicos Internacionais",
            resultado["fonte"],
        )

    def test_fallback_legado_usgs_restrito_ao_sciencebase(self):
        resultado, _capturado, orquestrador = self._resultado_responder(
            usar_usgs=True,
        )

        self.assertEqual(
            orquestrador.call_args.kwargs["regioes_selecionadas"],
            [assistant.OPCAO_USGS_INTERNACIONAL],
        )
        self.assertIn("usgs", resultado["dados"])

    def test_aliases_das_chaves_da_interface(self):
        regioes = [servico.OPCOES_REGIOES_INTERNACIONAIS[3]]
        resultado, _capturado, orquestrador = self._resultado_responder(
            intl_geo_enabled=True,
            intl_geo_regioes=regioes,
        )

        self.assertEqual(
            orquestrador.call_args.kwargs["regioes_selecionadas"],
            regioes,
        )
        self.assertIn("intl_geo", resultado["dados"])

        _resultado, _capturado, orquestrador = self._resultado_responder(
            usgs_enabled=True,
        )
        self.assertEqual(
            orquestrador.call_args.kwargs["regioes_selecionadas"],
            [assistant.OPCAO_USGS_INTERNACIONAL],
        )

    def test_prompt_contem_tabela_consolidada_e_origem(self):
        dados = {
            "intl_geo": {
                "fonte": "Serviços Geológicos Internacionais",
                "regioes": [servico.OPCOES_REGIOES_INTERNACIONAIS[3]],
                "por_fonte": {servico.FONTE_CANADA: 1},
                "registros": [_registro(
                    "Gold in Canada",
                    servico.FONTE_CANADA,
                    "https://exemplo.org/canada",
                )],
            }
        }

        texto = prompt_manager.montar_prompt_sistema(
            dados,
            texto_base="BASE",
            pergunta="ouro no Canadá",
        )

        self.assertIn("TABELA CONSOLIDADA DOS SERVIÇOS GEOLÓGICOS", texto)
        self.assertIn("NRCan / GSC (Canadá)", texto)
        self.assertIn("Gold in Canada", texto)

    def test_mapa_atribui_camada_internacional(self):
        feicoes = consolidar_pontos_mapa(
            "",
            [{
                "fonte": "intl_geo",
                "titulo": "Serviços Geológicos Internacionais",
                "registros": [_registro(
                    "Gold in Canada",
                    servico.FONTE_CANADA,
                    "https://exemplo.org/canada",
                    45.0,
                    -75.0,
                )],
            }],
        )

        self.assertEqual(len(feicoes), 1)
        self.assertEqual(feicoes[0]["camada"], "Serviços geológicos internacionais")
        self.assertEqual(feicoes[0]["cor_hex"], "#0F766E")

        # Também funciona quando o registro chega com o rótulo exato da
        # fonte, sem a chave interna do grupo ("Canadá" não pode ser
        # confundido com a camada "ana").
        feicoes = consolidar_pontos_mapa(
            "",
            [{
                "fonte": servico.FONTE_CANADA,
                "registros": [_registro(
                    "Gold in Canada",
                    servico.FONTE_CANADA,
                    "https://exemplo.org/canada",
                    45.0,
                    -75.0,
                )],
            }],
        )
        self.assertEqual(feicoes[0]["camada"], "Serviços geológicos internacionais")

    def test_parecer_abnt_identifica_o_servico(self):
        texto = gerar_parecer_markdown(
            "Ouro no Canadá",
            "Resposta de teste.",
            [{
                "fonte": "intl_geo",
                "registros": [_registro(
                    "Gold in Canada",
                    servico.FONTE_CANADA,
                    "https://exemplo.org/canada",
                    45.0,
                    -75.0,
                )],
            }],
            "Geologia Regional & Mapeamento Geológico",
        )

        self.assertIn("Gold in Canada", texto)
        self.assertIn("NRCan / GSC (Canadá)", texto)
        self.assertIn("Disponível em", texto)


if __name__ == "__main__":
    unittest.main()
