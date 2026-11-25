"""Testes da resolução espacial e do pacote offline por folha CIM (D2).

Cobrem a normalização de coordenadas, a recusa de inversão indevida, a
hierarquia 1:1.000.000 -> 1:25.000, a gravação atômica do pacote e a
consulta desconectada. Cada caso usa um SQLite temporário; o banco real
do usuário nunca é aberto.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters import spatial_cim
from services import db_service
from services.spatial_parser import (
    codigo_folha_cim,
    decodificar_folha_cim,
    extrair_feicoes_espaciais,
)

RAIZ = Path(__file__).resolve().parent.parent
BASE_TESTES = RAIZ / "build" / "_tmp_spatial_cim"


def preparar_pasta(nome):
    """Pasta de teste dentro do workspace, limpa antes de cada caso."""

    caminho = BASE_TESTES / nome
    shutil.rmtree(caminho, ignore_errors=True)
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


FEICOES = [
    {
        "nome": "Poço A",
        "camada": "Hidrogeologia (SIAGAS)",
        "fonte": "siagas",
        "lat": -3.10,
        "lon": -60.00,
        "folha_cim": "SA.21",
        "detalhe": "Poço tubular",
    },
    {
        "nome": "Estação B",
        "camada": "Hidrologia (ANA)",
        "fonte": "ana",
        "lat": -3.20,
        "lon": -59.90,
        "folha_cim": "SA.21",
        "detalhe": "Estação fluviométrica",
    },
    {
        "nome": "Fora da folha",
        "camada": "Hidrologia (ANA)",
        "fonte": "ana",
        "lat": -10.0,
        "lon": -50.0,
        "folha_cim": "SC.23",
        "detalhe": "Não pertence a SA.21",
    },
]


class BaseEspacial(unittest.TestCase):
    """Base com banco temporário inicializado."""

    def setUp(self):
        self.pasta = preparar_pasta(self._testMethodName)
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        self.db = self.pasta / "espacial.db"
        db_service.inicializar_banco(self.db)


class TestCoordenadas(BaseEspacial):
    """Normalização e validação de latitude/longitude."""

    def test_coordenada_valida_e_normalizada(self):
        resultado = spatial_cim.normalizar_coordenadas(-3.1234567, -60.0123456)

        self.assertTrue(resultado["ok"])
        self.assertFalse(resultado["invertida"])
        self.assertEqual(resultado["lat"], -3.123457)
        self.assertEqual(resultado["lon"], -60.012346)
        self.assertIn("S", resultado["formatado"])
        self.assertIn("W", resultado["formatado"])

    def test_par_sem_rotulo_invalido_e_invertido(self):
        resultado = spatial_cim.normalizar_coordenadas(120.0, -3.0)

        self.assertTrue(resultado["ok"])
        self.assertTrue(resultado["invertida"])
        self.assertEqual(resultado["lat"], -3.0)
        self.assertEqual(resultado["lon"], 120.0)

    def test_par_rotulado_nao_e_invertido(self):
        resultado = spatial_cim.normalizar_coordenadas(
            95.0, -60.0, rotulado=True
        )

        self.assertFalse(resultado["ok"])
        self.assertEqual(
            resultado["erro"], spatial_cim.ERRO_INVERSAO_INDEVIDA
        )
        self.assertTrue(resultado["inversao_suspeita"])

    def test_coordenada_ausente_e_fora_da_faixa(self):
        ausente = spatial_cim.normalizar_coordenadas("", None)
        self.assertEqual(ausente["erro"], spatial_cim.ERRO_COORDENADA_AUSENTE)

        invalida = spatial_cim.normalizar_coordenadas(10.0, 190.0)
        self.assertEqual(
            invalida["erro"], spatial_cim.ERRO_COORDENADA_INVALIDA
        )

    def test_virgula_decimal_e_aceita(self):
        resultado = spatial_cim.normalizar_coordenadas("-3,5", "-60,25")

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["lat"], -3.5)
        self.assertEqual(resultado["lon"], -60.25)


class TestHierarquiaCim(BaseEspacial):
    """Articulação cartográfica de 1:1.000.000 a 1:25.000."""

    def test_hierarquia_tem_seis_escalas(self):
        niveis = spatial_cim.hierarquia_cim(lat=-3.1, lon=-60.0)

        self.assertEqual(
            [nivel["escala"] for nivel in niveis],
            list(spatial_cim.ESCALAS_CIM),
        )
        self.assertEqual(niveis[0]["codigo"], "SA.21")
        self.assertEqual(niveis[-1]["escala"], "1:25.000")
        self.assertTrue(niveis[-1]["codigo"].startswith("SA.21-"))

    def test_cada_nivel_contem_o_ponto(self):
        for nivel in spatial_cim.hierarquia_cim(lat=-3.1, lon=-60.0):
            self.assertTrue(
                spatial_cim.folha_contem(nivel["codigo"], -3.1, -60.0),
                nivel["codigo"],
            )

    def test_codigo_de_1_50_mil_devolve_prefixos(self):
        niveis = spatial_cim.hierarquia_cim(codigo="SB.21-X-B-IV-1")

        self.assertEqual(len(niveis), 5)
        self.assertEqual(niveis[-1]["escala"], "1:50.000")
        self.assertEqual(niveis[-1]["codigo"], "SB.21-X-B-IV-1")

    def test_codigo_de_1_25_mil_e_aceito(self):
        folha = spatial_cim.decodificar_folha_cim("SC.22-Z-D-IV-3-2")

        self.assertIsNotNone(folha)
        self.assertEqual(folha["escala"], "1:25.000")

    def test_banda_i_decodifica_latitude_33_7_sul(self):
        # Regressão D2 -> D3: a banda I (32°–36°) cobre o extremo sul
        # do Brasil e precisa ser reconhecida pela articulação CIM.
        self.assertEqual(codigo_folha_cim(-33.7, -53.4), "SI.22")

        folha = decodificar_folha_cim("SI.22")
        self.assertIsNotNone(folha)
        self.assertEqual(folha["escala"], "1:1.000.000")
        self.assertEqual(folha["lat_min"], -36.0)
        self.assertEqual(folha["lat_max"], -32.0)
        self.assertEqual(folha["lon_min"], -54.0)
        self.assertEqual(folha["lon_max"], -48.0)
        self.assertTrue(spatial_cim.folha_contem("SI.22", -33.7, -53.4))

        niveis = spatial_cim.hierarquia_cim(lat=-33.7, lon=-53.4)
        self.assertEqual(niveis[0]["codigo"], "SI.22")
        self.assertEqual(len(niveis), 6)
        self.assertTrue(niveis[-1]["codigo"].startswith("SI.22-"))

        feicoes = extrair_feicoes_espaciais("Folha SI.22, no Sul.")
        self.assertTrue(
            any(
                feicao.get("folha_cim") == "SI.22"
                for feicao in feicoes
            ),
            feicoes,
        )

    def test_codigo_invalido_nao_quebra(self):
        resultado = spatial_cim.resolver_consulta_espacial(codigo="ZZ.00")

        self.assertFalse(resultado["ok"])
        self.assertEqual(
            resultado["erro"], spatial_cim.ERRO_FOLHA_INVALIDA
        )


class TestResolucao(BaseEspacial):
    """Resolução completa, com disponibilidade do pacote."""

    def test_resolucao_por_coordenada(self):
        resultado = spatial_cim.resolver_consulta_espacial(
            lat=-3.1,
            lon=-60.0,
            caminho_db=self.db,
        )

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["folha_cim"], "SA.21")
        self.assertEqual(len(resultado["hierarquia"]), 6)
        self.assertFalse(resultado["pacote_disponivel"])

    def test_pacote_em_folha_detalhada_e_reconhecido(self):
        # O pacote pode ter sido salvo em SA.21-V-B (1:250.000); a
        # resolução de um ponto dentro dela precisa enxergar o pacote,
        # não apenas o da folha 1:1.000.000.
        feicao = {
            "nome": "Poço detalhado",
            "camada": "Hidrogeologia (SIAGAS)",
            "fonte": "siagas",
            "lat": -0.5,
            "lon": -57.5,
            "folha_cim": "SA.21-V-B",
            "detalhe": "Registro da folha detalhada",
        }
        pacote = spatial_cim.salvar_pacote_offline(
            "SA.21-V-B",
            feicoes=[feicao],
            caminho_db=self.db,
        )
        self.assertTrue(pacote["ok"])

        por_coordenada = spatial_cim.resolver_consulta_espacial(
            lat=-0.5,
            lon=-57.5,
            caminho_db=self.db,
        )

        self.assertTrue(por_coordenada["ok"])
        self.assertTrue(por_coordenada["pacote_disponivel"])
        self.assertEqual(
            por_coordenada["pacote_folha"], "SA.21-V-B"
        )
        self.assertIn(
            "SA.21-V-B", por_coordenada["pacotes_disponiveis"]
        )
        self.assertIn(
            "SA.21-V-B",
            [nivel["codigo"] for nivel in por_coordenada["hierarquia"]],
        )

        por_codigo = spatial_cim.resolver_consulta_espacial(
            codigo="SA.21-V-B",
            caminho_db=self.db,
        )

        self.assertTrue(por_codigo["pacote_disponivel"])
        self.assertEqual(por_codigo["pacote_folha"], "SA.21-V-B")

    def test_resolucao_por_folha(self):
        resultado = spatial_cim.resolver_consulta_espacial(
            codigo="SB.21-X-B",
            caminho_db=self.db,
        )

        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["escala"], "1:250.000")
        self.assertEqual(resultado["folha_cim"], "SB.21")
        self.assertEqual(len(resultado["hierarquia"]), 3)


class TestPacoteOffline(BaseEspacial):
    """Manifesto, totais por fonte e consulta 100% desconectada."""

    def _salvar(self, feicoes=FEICOES, versao="v1"):
        return spatial_cim.salvar_pacote_offline(
            "SA.21",
            feicoes=feicoes,
            collected_at="2026-11-22T10:00:00-04:00",
            source_version=versao,
            caminho_db=self.db,
        )

    def test_manifesto_tem_cim_code_collected_at_e_totais(self):
        pacote = self._salvar()
        manifesto = pacote["manifesto"]["manifesto"]

        self.assertEqual(manifesto["cim_code"], "SA.21")
        self.assertEqual(
            manifesto["collected_at"], "2026-11-22T10:00:00-04:00"
        )
        self.assertEqual(manifesto["source_version"], "v1")
        self.assertEqual(manifesto["total_registros"], 2)
        self.assertEqual(
            manifesto["totais_por_fonte"],
            {"siagas": 1, "ana": 1},
        )

        self.assertTrue(
            db_service.pacote_offline_disponivel("SA.21", self.db)
        )
        resumo = db_service.resumo_memoria(self.db)
        self.assertEqual(resumo["pacotes_offline"], 1)
        self.assertEqual(resumo["cache_espacial"], 2)

    def test_consulta_desconectada_nao_chama_rede(self):
        self._salvar()

        with patch(
            "requests.get",
            side_effect=AssertionError("nenhuma rede deveria ser usada"),
        ), patch(
            "requests.post",
            side_effect=AssertionError("nenhuma rede deveria ser usada"),
        ):
            consulta = spatial_cim.consultar_pacote_offline(
                "SA.21", caminho_db=self.db
            )

        self.assertTrue(consulta["disponivel"])
        self.assertEqual(len(consulta["feicoes"]), 2)
        self.assertEqual(
            {feicao["fonte"] for feicao in consulta["feicoes"]},
            {"siagas", "ana"},
        )

    def test_filtro_por_fonte(self):
        self._salvar()
        consulta = spatial_cim.consultar_pacote_offline(
            "SA.21", fonte="ana", caminho_db=self.db
        )

        self.assertEqual(len(consulta["feicoes"]), 1)
        self.assertEqual(consulta["feicoes"][0]["fonte"], "ana")

    def test_atualizacao_substitui_snapshot_anterior(self):
        self._salvar()
        atualizado = self._salvar(
            feicoes=[FEICOES[1]],
            versao="v2",
        )
        manifesto = atualizado["manifesto"]["manifesto"]

        self.assertEqual(manifesto["source_version"], "v2")
        self.assertEqual(manifesto["total_registros"], 1)
        self.assertEqual(manifesto["totais_por_fonte"], {"ana": 1})

        resumo = db_service.resumo_memoria(self.db)
        self.assertEqual(resumo["cache_espacial"], 1)

    def test_pacote_sem_registros_nao_substitui_anterior(self):
        self._salvar()
        antes = spatial_cim.obter_pacote_offline("SA.21", self.db)

        vazio = spatial_cim.salvar_pacote_offline(
            "SB.21",
            feicoes=FEICOES,
            source_version="v2",
            caminho_db=self.db,
        )

        self.assertFalse(vazio["ok"])
        self.assertEqual(
            vazio["erro"], spatial_cim.ERRO_PACOTE_SEM_DADOS
        )

        # Nenhuma folha foi criada ou apagada pela tentativa vazia.
        self.assertIsNone(
            spatial_cim.obter_pacote_offline("SB.21", self.db)
        )
        depois = spatial_cim.obter_pacote_offline("SA.21", self.db)
        self.assertEqual(
            depois["manifesto"]["total_registros"],
            antes["manifesto"]["total_registros"],
        )
        self.assertEqual(
            depois["manifesto"]["source_version"],
            antes["manifesto"]["source_version"],
        )

    def test_remocao_limpa_manifesto_e_cache(self):
        self._salvar()
        self.assertTrue(
            spatial_cim.remover_pacote_offline("SA.21", self.db)
        )
        self.assertFalse(
            spatial_cim.pacote_offline_disponivel("SA.21", self.db)
        )
        self.assertIsNone(
            spatial_cim.obter_pacote_offline("SA.21", self.db)
        )

    def test_folha_invalida_nao_grava(self):
        pacote = spatial_cim.salvar_pacote_offline(
            "ZZ.00",
            feicoes=FEICOES,
            caminho_db=self.db,
        )

        self.assertFalse(pacote["ok"])
        self.assertEqual(
            pacote["erro"], spatial_cim.ERRO_FOLHA_INVALIDA
        )
        self.assertEqual(db_service.resumo_memoria(self.db)["cache_espacial"], 0)


if __name__ == "__main__":
    unittest.main()
