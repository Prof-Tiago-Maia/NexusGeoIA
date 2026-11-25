"""Testes unitários da camada de internacionalização (PT-BR / EN).

Não dependem de navegador, de servidor Streamlit nem de rede: exercitam
apenas ``utils.i18n``, cujo estado padrão (fora de um script) é o
Português do Brasil.
"""

import unittest

from config import (
    APP_DISPLAY_NAME,
    APP_NAME,
    APP_VERSION,
    NOME_APLICATIVO,
)
from utils.i18n import (
    IDIOMA_PADRAO,
    INSTRUCAO_IDIOMA_RESPOSTA,
    PERFIS_EN,
    REGIOES_EN,
    TEXTOS_I18N,
    idioma_atual,
    instrucao_idioma_resposta,
    normalizar_idioma,
    perfil_do_rotulo,
    regiao_do_rotulo,
    rotulo_curto_perfil,
    rotulo_perfil,
    rotulo_regiao,
    t,
    tf,
)


class TestIdentidadeOficial(unittest.TestCase):
    """Nome e versão oficiais são a fonte única da verdade."""

    def test_nome_e_versao(self):
        self.assertEqual(APP_NAME, "NexusGeo IA")
        self.assertEqual(APP_VERSION, "1.0.0")
        self.assertEqual(APP_DISPLAY_NAME, "NexusGeo IA v1.0.0")

    def test_diretorio_localappdata_sem_espacos(self):
        self.assertEqual(NOME_APLICATIVO, "NexusGeoIA")
        self.assertEqual(NOME_APLICATIVO, APP_NAME.replace(" ", ""))

    def test_titulo_das_duas_linguas_usa_o_nome_oficial(self):
        self.assertEqual(t("titulo", "pt"), APP_NAME)
        self.assertEqual(t("titulo", "en"), APP_NAME)


class TestDicionario(unittest.TestCase):
    """Integridade do dicionário e do fallback da função ``t``."""

    def test_portugues_e_ingles_tem_as_mesmas_chaves(self):
        chaves_pt = set(TEXTOS_I18N["pt"])
        chaves_en = set(TEXTOS_I18N["en"])

        self.assertTrue(chaves_pt)
        self.assertEqual(chaves_pt - chaves_en, set())
        self.assertEqual(chaves_en - chaves_pt, set())

    def test_t_le_o_idioma_padrao_fora_do_streamlit(self):
        self.assertEqual(idioma_atual(), IDIOMA_PADRAO)
        self.assertEqual(t("novo_chat"), "➕ Novo Chat")

    def test_t_respeita_o_idioma_explicito(self):
        self.assertEqual(t("novo_chat", "pt"), "➕ Novo Chat")
        self.assertEqual(t("novo_chat", "en"), "➕ New Chat")

    def test_t_faz_fallback_para_portugues_quando_a_chave_falta(self):
        # Uma chave existente só em pt não deve quebrar a interface.
        TEXTOS_I18N["pt"]["teste_fallback"] = "texto em português"
        self.addCleanup(
            TEXTOS_I18N["pt"].pop,
            "teste_fallback",
            None,
        )

        self.assertNotIn("teste_fallback", TEXTOS_I18N["en"])
        self.assertEqual(t("teste_fallback", "en"), "texto em português")

    def test_t_devolve_a_propria_chave_quando_nao_existe(self):
        self.assertEqual(t("chave_inexistente_xyz", "en"),
                         "chave_inexistente_xyz")

    def test_normalizar_idioma_cai_no_padrao(self):
        self.assertEqual(normalizar_idioma("EN"), "en")
        self.assertEqual(normalizar_idioma(""), "pt")
        self.assertEqual(normalizar_idioma("es"), "pt")
        self.assertEqual(normalizar_idioma(None), "pt")

    def test_tf_preenche_marcadores_e_preserva_os_ausentes(self):
        self.assertEqual(
            tf("historico_contagem", "en", n=3),
            "3 saved conversation(s) · newest first",
        )
        # Marcador sem valor não levanta erro: o texto fica como está.
        self.assertEqual(
            tf("historico_contagem", "en"),
            "{n} saved conversation(s) · newest first",
        )


class TestTextosTraduzidos(unittest.TestCase):
    """Cobertura dos blocos pedidos na interface bilíngue."""

    def test_cabecalho_e_status(self):
        for idioma, esperado in (
            ("pt", "Ollama online · host"),
            ("en", "Ollama offline · host"),
        ):
            chave = "ollama_online" if idioma == "pt" else "ollama_offline"
            self.assertEqual(tf(chave, idioma, host="host"), esperado)

        self.assertIn(
            "NexusGeo",
            t("titulo", "pt"),
        )
        self.assertIn("NexusGeo", t("titulo", "en"))
        self.assertEqual(
            t("subtitulo", "pt"),
            "Plataforma Integrada de Dados Geocientíficos e IA Local",
        )
        self.assertEqual(
            t("subtitulo", "en"),
            "Integrated Geoscientific Data & Local AI Platform",
        )

    def test_secoes_da_barra_lateral(self):
        for chave in (
            "secao_documentos",
            "secao_historico",
            "secao_fontes",
            "secao_perfil",
            "config_avancadas",
        ):
            self.assertNotEqual(t(chave, "pt"), t(chave, "en"))

    def test_botao_novo_chat(self):
        self.assertEqual(t("novo_chat", "pt"), "➕ Novo Chat")
        self.assertEqual(t("novo_chat", "en"), "➕ New Chat")

    def test_guia_rapido_completo(self):
        for chave in (
            "guia_titulo",
            "guia_intro",
            "guia_passo_1_titulo",
            "guia_passo_2_titulo",
            "guia_passo_3_titulo",
            "guia_passo_4_titulo",
            "guia_combinacao_titulo",
            "guia_combinacao_intro",
            "guia_combinacao_1_titulo",
            "guia_combinacao_1_texto",
            "guia_combinacao_2_titulo",
            "guia_combinacao_2_texto",
            "guia_combinacao_3_titulo",
            "guia_combinacao_3_texto",
            "guia_combinacao_4_titulo",
            "guia_combinacao_4_texto",
            "guia_dica",
        ):
            self.assertNotEqual(t(chave, "pt"), t(chave, "en"))

        self.assertIn("Como usar", t("guia_titulo", "pt"))
        self.assertIn("How to use", t("guia_titulo", "en"))

    def test_dicas_de_combinacao_de_fontes_bilingues(self):
        texto_pt = " ".join(
            t(chave, "pt")
            for chave in (
                "guia_combinacao_1_titulo",
                "guia_combinacao_1_texto",
                "guia_combinacao_2_titulo",
                "guia_combinacao_2_texto",
                "guia_combinacao_3_titulo",
                "guia_combinacao_3_texto",
                "guia_combinacao_4_titulo",
                "guia_combinacao_4_texto",
            )
        )
        texto_en = " ".join(
            t(chave, "en")
            for chave in (
                "guia_combinacao_1_titulo",
                "guia_combinacao_1_texto",
                "guia_combinacao_2_titulo",
                "guia_combinacao_2_texto",
                "guia_combinacao_3_titulo",
                "guia_combinacao_3_texto",
                "guia_combinacao_4_titulo",
                "guia_combinacao_4_texto",
            )
        )

        for termo in (
            "Serviços Geológicos Internacionais",
            "OpenAlex",
            "Macrostrat",
            "SGB / RIGeo",
            "GeoSGB",
            "ANM / SIGMINE",
            "ANA / HidroWeb",
            "SIAGAS",
            "GeoNet",
            "GSJ",
            "USGS",
            "Base Documental Local",
        ):
            self.assertIn(termo, texto_pt)

        for termo in (
            "International Geological Surveys",
            "OpenAlex",
            "Macrostrat",
            "SGB / RIGeo",
            "GeoSGB",
            "ANM / SIGMINE",
            "ANA / HidroWeb",
            "SIAGAS",
            "GeoNet",
            "GSJ",
            "USGS",
            "Local Document Base",
        ):
            self.assertIn(termo, texto_en)

    def test_parecer_e_planilhas(self):
        self.assertEqual(
            t("parecer_expander", "pt"),
            "📄 Exportar Parecer Técnico",
        )
        self.assertEqual(
            t("parecer_expander", "en"),
            "📄 Export Technical Report",
        )
        self.assertEqual(t("baixar_csv", "pt"), "Baixar CSV")
        self.assertEqual(t("baixar_csv", "en"), "Download CSV")

    def test_mensagens_de_erro_e_aviso(self):
        self.assertIn("Não foi possível", t("erro_consulta", "pt"))
        self.assertIn("could not be completed", t("erro_consulta", "en"))
        self.assertIn("Histórico apagado", tf(
            "aviso_historico_apagado", "pt", n=2
        ))
        self.assertIn("History deleted", tf(
            "aviso_historico_apagado", "en", n=2
        ))


class TestRegioesEPerfis(unittest.TestCase):
    """Rótulos traduzíveis sem alterar os valores canônicos."""

    def test_regiao_todas_traduzida(self):
        canonica = "🌎 Todas as Regiões (Global)"

        self.assertEqual(rotulo_regiao(canonica, "pt"), canonica)
        self.assertEqual(
            rotulo_regiao(canonica, "en"),
            "🌎 All Regions (Global)",
        )
        # O valor canônico continua sendo a chave usada pelos conectores.
        self.assertIn(canonica, REGIOES_EN)

    def test_regiao_desconhecida_permanece_intacta(self):
        self.assertEqual(
            rotulo_regiao("Região inventada", "en"),
            "Região inventada",
        )

    def test_regiao_do_rotulo_reverte_os_dois_idiomas(self):
        canonica = "🇨🇦 Canadá (NRCan / GSC)"

        self.assertEqual(regiao_do_rotulo(canonica), canonica)
        self.assertEqual(
            regiao_do_rotulo(rotulo_regiao(canonica, "en")),
            canonica,
        )
        self.assertIsNone(regiao_do_rotulo("Não é uma região"))

    def test_perfil_do_rotulo_reverte_os_dois_idiomas(self):
        canonico = "Geotecnia & Geologia de Engenharia"

        self.assertEqual(perfil_do_rotulo(canonico), canonico)
        self.assertEqual(
            perfil_do_rotulo(rotulo_perfil(canonico, "en")),
            canonico,
        )
        self.assertIsNone(perfil_do_rotulo("Perfil inexistente"))

    def test_perfis_tem_nome_curto_e_descricao_em_ingles(self):
        perfil = "Hidrogeologia & Recursos Hídricos"

        self.assertEqual(rotulo_perfil(perfil, "pt"), perfil)
        self.assertEqual(
            rotulo_perfil(perfil, "en"),
            "Hydrogeology & Water Resources",
        )
        self.assertTrue(rotulo_curto_perfil(perfil, "en"))
        self.assertTrue(PERFIS_EN[perfil]["descricao"])


class TestInstrucaoDoLLM(unittest.TestCase):
    """A instrução de idioma exigida no system prompt."""

    def test_portugues_exige_pt_br_e_preserva_citacoes(self):
        instrucao = instrucao_idioma_resposta("pt")

        self.assertIn("Português do Brasil", instrucao)
        self.assertIn("citações", instrucao)
        self.assertIn("nomes próprios", instrucao)
        self.assertIn("tabelas", instrucao)

    def test_ingles_exige_ingles_tecnico_e_preserva_citacoes(self):
        instrucao = instrucao_idioma_resposta("en")

        self.assertIn("English", instrucao)
        self.assertIn("quotations", instrucao)
        self.assertIn("proper names", instrucao)
        self.assertIn("tables", instrucao)

    def test_idioma_invalido_cai_no_portugues(self):
        self.assertEqual(
            instrucao_idioma_resposta("fr"),
            INSTRUCAO_IDIOMA_RESPOSTA["pt"],
        )


if __name__ == "__main__":
    unittest.main()
