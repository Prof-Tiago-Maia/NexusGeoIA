"""Testes do dataset comportamental bilíngue (PT-BR/EN).

Cobrem esquema, paridade dos pares, determinismo, recomputação pelo
oráculo e a guarda do banco real. Nenhum teste acessa rede ou treina
pesos.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from finetuning import contrato, gerador, oraculo
from tests import _db_intocado

# Versão 1 congelada: o dataset original é material histórico e não pode
# ser regravado pela geração da v2. Os digests foram capturados antes da
# expansão e são a prova de que os bytes permaneceram idênticos.
V1_JSONL = Path(gerador.PASTA_DATASETS) / "nexusgeoia_behavior_v1.jsonl"
V1_MANIFESTO = (
    Path(gerador.PASTA_DATASETS)
    / "nexusgeoia_behavior_v1.manifest.json"
)
V1_SHA256 = "ed4edd9b6fd317cabc10c712edf3709013a1d98479be966e00d4086d2006fe5f"
V1_MANIFESTO_SHA256 = (
    "b78652e4d96747b3d569e754b03ed25c5d8c881d03aa525ac410b4d73a38e222"
)


def _mesmo_valor(esquerda, direita):
    if isinstance(esquerda, float) or isinstance(direita, float):
        if esquerda is None or direita is None:
            return esquerda is None and direita is None

        return abs(esquerda - direita) <= 1e-9

    return esquerda == direita


class TestDatasetComportamental(unittest.TestCase):
    """Valida o artefato gerado e a sua rastreabilidade."""

    @classmethod
    def setUpClass(cls):
        cls.registros = gerador.carregar_registros()
        cls.por_id = {registro["id"]: registro for registro in cls.registros}

    def test_arquivo_e_manifesto_existem(self):
        self.assertTrue(gerador.ARQUIVO_PADRAO.is_file())
        self.assertTrue(gerador.MANIFESTO_PADRAO.is_file())
        self.assertEqual(
            gerador.ARQUIVO_PADRAO.name,
            "nexusgeoia_behavior_v2.jsonl",
        )
        self.assertEqual(contrato.VERSAO_DATASET, "2.0.0")

    def test_dataset_v1_original_permanece_intacto(self):
        self.assertTrue(V1_JSONL.is_file())
        self.assertTrue(V1_MANIFESTO.is_file())
        self.assertEqual(
            hashlib.sha256(V1_JSONL.read_bytes()).hexdigest(),
            V1_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(V1_MANIFESTO.read_bytes()).hexdigest(),
            V1_MANIFESTO_SHA256,
        )

        manifesto = json.loads(V1_MANIFESTO.read_text(encoding="utf-8"))
        self.assertEqual(manifesto["nome"], "nexusgeoia_behavior_v1")
        self.assertEqual(manifesto["versao"], "1.0.0")
        self.assertEqual(manifesto["total"], 212)
        self.assertEqual(manifesto["sha256_registros"], V1_SHA256)

    def test_todas_as_tarefas_tem_volume_minimo(self):
        contagem = Counter(registro["tarefa"] for registro in self.registros)

        for tarefa in contrato.TAREFAS:
            self.assertGreaterEqual(contagem[tarefa], 50, tarefa)

    def test_idiomas_equilibrados(self):
        contagem = Counter(registro["idioma"] for registro in self.registros)
        self.assertEqual(contagem["pt"], contagem["en"])

    def test_familias_pedagogicas_presentes_em_cada_tarefa(self):
        for tarefa in contrato.TAREFAS:
            familias = {
                registro["metadados"]["familia"]
                for registro in self.registros
                if registro["tarefa"] == tarefa
            }
            self.assertEqual(familias, set(contrato.FAMILIAS), tarefa)

    def test_esquema_de_todos_os_registros(self):
        for registro in self.registros:
            with self.subTest(id=registro["id"]):
                self.assertEqual(
                    contrato.validar_registro(registro),
                    [],
                )

    def test_ids_unicos(self):
        self.assertEqual(
            len(self.por_id),
            len(self.registros),
        )

    def test_pares_bilingues_completos_e_equivalentes(self):
        pares = {}

        for registro in self.registros:
            pares.setdefault(registro["metadados"]["par"], {})[
                registro["idioma"]
            ] = registro

        self.assertEqual(len(pares), len(self.registros) // 2)

        for par, idiomas in pares.items():
            with self.subTest(par=par):
                self.assertEqual(set(idiomas), set(contrato.IDIOMAS))
                pt = idiomas["pt"]
                en = idiomas["en"]
                self.assertEqual(pt["tarefa"], en["tarefa"])

                if pt["tarefa"] != contrato.TAREFA_SONDAGEM:
                    self.assertEqual(
                        pt["saida_esperada"],
                        en["saida_esperada"],
                    )
                    continue

                for campo in (
                    "de_m",
                    "ate_m",
                    "espessura_m",
                    "situacao",
                    "motivo",
                    "unidade",
                    "erro",
                ):
                    self.assertTrue(
                        _mesmo_valor(
                            pt["saida_esperada"].get(campo),
                            en["saida_esperada"].get(campo),
                        ),
                        f"{par}:{campo}",
                    )

    def test_oraculo_recomputa_todo_gabarito(self):
        for registro in self.registros:
            with self.subTest(id=registro["id"]):
                self.assertEqual(
                    oraculo.prever(registro),
                    registro["saida_esperada"],
                )

    def test_geracao_deterministica(self):
        primeira = gerador.serializar(gerador.gerar_registros())
        segunda = gerador.serializar(gerador.gerar_registros())
        self.assertEqual(primeira, segunda)
        self.assertEqual(
            gerador.hash_registros(gerador.gerar_registros()),
            gerador.hash_registros(self.registros),
        )

    def test_manifesto_confere_com_arquivo(self):
        manifesto = json.loads(
            Path(gerador.MANIFESTO_PADRAO).read_text(encoding="utf-8")
        )

        self.assertEqual(manifesto["nome"], "nexusgeoia_behavior_v2")
        self.assertEqual(manifesto["versao"], "2.0.0")
        self.assertEqual(manifesto["total"], len(self.registros))
        self.assertEqual(
            manifesto["sha256_registros"],
            gerador.hash_registros(self.registros),
        )
        self.assertEqual(
            manifesto["por_idioma"],
            dict(Counter(r["idioma"] for r in self.registros)),
        )

    def test_roteamento_usa_ana_e_triagem(self):
        ana = [
            registro
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_WORKFLOW
            and "HidroWeb" in registro["entrada"]
            and registro["idioma"] == "pt"
        ]
        self.assertEqual(ana[0]["saida_esperada"]["intencao"], "ANA_ONLY")

        triagem = [
            registro
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_WORKFLOW
            and registro["entrada"].endswith("Pergunta: Triagem.")
        ]
        self.assertEqual(
            triagem[0]["saida_esperada"]["workflow"],
            "triagem_area",
        )

    def test_sondagem_cobre_metros_centimetros_e_negativos(self):
        caso = self.por_id["sd-pt-001"]["saida_esperada"]
        self.assertEqual(caso["de_m"], 0.0)
        self.assertEqual(caso["ate_m"], 2.5)
        self.assertEqual(caso["espessura_m"], 2.5)

        centimetros = [
            registro["saida_esperada"]
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_SONDAGEM
            and registro["saida_esperada"].get("unidade") == "cm"
        ]
        self.assertTrue(centimetros)

        erros = [
            registro
            for registro in self.registros
            if registro["saida_esperada"].get("situacao")
            == "erro_contrato"
        ]
        self.assertTrue(erros)

        negativos = [
            registro
            for registro in self.registros
            if registro["saida_esperada"].get("motivo")
            == "ate_nao_maior_que_de"
        ]
        self.assertTrue(negativos)

    def test_governanca_cobre_pass_hold_fail_e_falha_de_fonte(self):
        vereditos = {
            registro["saida_esperada"]["veredito"]
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_GOVERNANCA
        }
        self.assertEqual(vereditos, set(contrato.VEREDITOS_GOVERNANCA))

        motivos = {
            registro["saida_esperada"]["motivo"]
            for registro in self.registros
            if registro["tarefa"] == contrato.TAREFA_GOVERNANCA
        }
        self.assertIn("observado_sem_evidencia", motivos)
        self.assertIn("evidencia_desconhecida", motivos)
        self.assertIn("texto_livre", motivos)
        self.assertIn("fonte_timeout", motivos)

    def test_dataset_v2_tem_300_registros_e_150_pares(self):
        self.assertEqual(len(self.registros), 300)
        self.assertEqual(
            len({r["metadados"]["par"] for r in self.registros}),
            150,
        )
        self.assertEqual(
            Counter(r["idioma"] for r in self.registros),
            Counter({"pt": 150, "en": 150}),
        )

    def test_sondagem_v2_cobre_unidades_e_milhar(self):
        # Cabeçalho "(m)": já está em metros, não divide.
        metros = self.por_id["sd-pt-038"]["saida_esperada"]
        self.assertEqual(metros["ate_m"], 3.75)
        self.assertEqual(metros["unidade"], "m")

        # Coluna Unidade em cm: converte 250 cm para 2,5 m.
        centimetros = self.por_id["sd-pt-040"]["saida_esperada"]
        self.assertEqual(centimetros["de_m"], 0.0)
        self.assertEqual(centimetros["ate_m"], 2.5)
        self.assertEqual(centimetros["unidade"], "cm")

        # Cabeçalho "(cm)" com dois limites: 100 cm -> 1 m.
        cabecalho_cm = self.por_id["sd-pt-041"]["saida_esperada"]
        self.assertEqual(cabecalho_cm["de_m"], 1.0)
        self.assertEqual(cabecalho_cm["ate_m"], 2.5)
        self.assertEqual(cabecalho_cm["espessura_m"], 1.5)

        # Unidades mistas na linha: unidade canônica "m/cm".
        misto = self.por_id["sd-pt-042"]["saida_esperada"]
        self.assertEqual(misto["unidade"], "m/cm")
        self.assertEqual(misto["ate_m"], 2.5)

        # Separador de milhar pt-BR: 12.345,6 -> 12345.6 (não 12,3456).
        milhar = self.por_id["sd-pt-044"]["saida_esperada"]
        self.assertEqual(milhar["de_m"], 12345.6)
        self.assertEqual(milhar["ate_m"], 12346.0)
        self.assertEqual(milhar["espessura_m"], 0.4)

    def test_sondagem_v2_preserva_sinal_e_nao_inventa_numero(self):
        negativo = self.por_id["sd-pt-045"]["saida_esperada"]
        self.assertEqual(negativo["de_m"], -0.5)
        self.assertEqual(negativo["ate_m"], 1.5)
        self.assertEqual(negativo["situacao"], "invalido")
        self.assertEqual(negativo["motivo"], "de_negativo")

        invalido = self.por_id["sd-pt-046"]["saida_esperada"]
        self.assertIsNone(invalido["de_m"])
        self.assertEqual(invalido["ate_m"], 2.0)
        self.assertIsNone(invalido["espessura_m"])
        self.assertEqual(invalido["motivo"], "de_invalido")

        unidade = self.por_id["sd-pt-047"]["saida_esperada"]
        self.assertIsNone(unidade["de_m"])
        self.assertIsNone(unidade["ate_m"])
        self.assertEqual(unidade["unidade"], "")
        self.assertEqual(unidade["motivo"], "unidade_invalida")

    def test_sondagem_v2_separa_erro_contrato_de_linha(self):
        sem_ate = self.por_id["sd-pt-049"]["saida_esperada"]
        self.assertEqual(sem_ate["situacao"], "erro_contrato")
        self.assertEqual(sem_ate["erro"], "cabecalhos_obrigatorios")
        self.assertNotIn("motivo", sem_ate)

        desalinhada = self.por_id["sd-pt-050"]["saida_esperada"]
        self.assertEqual(desalinhada["situacao"], "erro_contrato")
        self.assertEqual(desalinhada["erro"], "tabela_desalinhada")
        self.assertNotIn("motivo", desalinhada)

        linha = self.por_id["sd-pt-047"]["saida_esperada"]
        self.assertEqual(linha["situacao"], "invalido")
        self.assertTrue(linha["motivo"])
        self.assertNotIn("erro", linha)

    def test_sondagem_v2_cobre_sobreposicao_e_lacuna(self):
        sobreposta = self.por_id["sd-pt-051"]["saida_esperada"]
        self.assertEqual(sobreposta["situacao"], "sobreposicao")
        self.assertEqual(sobreposta["de_m"], 2.0)
        self.assertEqual(sobreposta["ate_m"], 4.0)
        self.assertEqual(sobreposta["motivo"], "")

        lacuna = self.por_id["sd-pt-052"]["saida_esperada"]
        self.assertEqual(lacuna["situacao"], "lacuna")
        self.assertEqual(lacuna["de_m"], 5.0)
        self.assertEqual(lacuna["ate_m"], 6.0)
        self.assertEqual(lacuna["motivo"], "")

        # Vários intervalos consecutivos e vários furos continuam válidos.
        self.assertEqual(
            self.por_id["sd-pt-053"]["saida_esperada"]["situacao"],
            "valido",
        )
        self.assertEqual(
            self.por_id["sd-pt-054"]["saida_esperada"]["situacao"],
            "valido",
        )

    def test_governanca_v2_nao_premia_otimismo(self):
        inferida_valida = self.por_id["gv-pt-030"]["saida_esperada"]
        self.assertEqual(inferida_valida["veredito"], "PASS")
        self.assertEqual(inferida_valida["classificacoes"], ["INFERRED"])

        evidencia_fantasma = self.por_id["gv-pt-032"]["saida_esperada"]
        self.assertEqual(evidencia_fantasma["veredito"], "HOLD")
        self.assertEqual(
            evidencia_fantasma["motivo"],
            "evidencia_desconhecida",
        )
        self.assertEqual(
            evidencia_fantasma["classificacoes"],
            ["INFERRED"],
        )

        sem_texto = self.por_id["gv-pt-033"]["saida_esperada"]
        self.assertEqual(sem_texto["veredito"], "HOLD")
        self.assertEqual(sem_texto["motivo"], "contrato_invalido")
        self.assertEqual(sem_texto["classificacoes"], [])

        sem_resposta = self.por_id["gv-pt-036"]["saida_esperada"]
        self.assertEqual(sem_resposta["veredito"], "FAIL")
        self.assertEqual(sem_resposta["motivo"], "resposta_vazia")
        self.assertEqual(sem_resposta["classificacoes"], [])

        fonte_desconhecida = self.por_id["gv-pt-038"]["saida_esperada"]
        self.assertEqual(fonte_desconhecida["veredito"], "HOLD")
        self.assertEqual(
            fonte_desconhecida["motivo"],
            "fonte_indisponivel",
        )
        self.assertEqual(fonte_desconhecida["classificacoes"], [])

        fail_declarado = self.por_id["gv-pt-042"]["saida_esperada"]
        self.assertEqual(fail_declarado["veredito"], "FAIL")
        self.assertEqual(fail_declarado["motivo"], "falha_declarada")
        self.assertEqual(fail_declarado["classificacoes"], [])

    def test_governanca_v2_classificacoes_vazias_quando_cabivel(self):
        vazio = self.por_id["gv-pt-035"]["saida_esperada"]
        self.assertEqual(vazio["veredito"], "PASS")
        self.assertEqual(vazio["classificacoes"], [])

        fonte_livre = self.por_id["gv-pt-039"]["saida_esperada"]
        self.assertEqual(fonte_livre["formato"], "texto_livre")
        self.assertEqual(fonte_livre["motivo"], "fonte_timeout")
        self.assertEqual(fonte_livre["classificacoes"], [])

        veredito_invalido = self.por_id["gv-pt-037"]["saida_esperada"]
        self.assertEqual(veredito_invalido["veredito"], "HOLD")
        self.assertEqual(
            veredito_invalido["motivo"],
            "veredito_invalido",
        )
        self.assertEqual(
            veredito_invalido["classificacoes"],
            ["INFERRED"],
        )

        aliases = self.por_id["gv-pt-041"]["saida_esperada"]
        self.assertEqual(aliases["formato"], "contrato")
        self.assertEqual(aliases["veredito"], "PASS")
        self.assertEqual(aliases["classificacoes"], ["OBSERVED"])

    def test_workflow_v2_precedencia_e_hibrido(self):
        # Sondagem vence hidrogeologia e triagem quando há furo.
        self.assertEqual(
            self.por_id["wf-pt-041"]["saida_esperada"],
            {"workflow": "sondagem", "intencao": "RIGEO_ONLY"},
        )
        # Hidrogeologia vence triagem quando o aquífero é citado.
        self.assertEqual(
            self.por_id["wf-pt-042"]["saida_esperada"],
            {"workflow": "hidrogeologia", "intencao": "RIGEO_ONLY"},
        )
        # "ANA" em maiúsculas sem geologia/documento é rota exclusiva.
        self.assertEqual(
            self.por_id["wf-pt-043"]["saida_esperada"],
            {"workflow": "hidrogeologia", "intencao": "ANA_ONLY"},
        )
        # HIBRIDO exige RAG e SGB reais: PDF + geologia.
        self.assertEqual(
            self.por_id["wf-pt-044"]["saida_esperada"],
            {"workflow": "triagem_area", "intencao": "HIBRIDO"},
        )
        # Documento + tema sem termo SGB continua LOCAL_ONLY.
        self.assertEqual(
            self.por_id["wf-pt-045"]["saida_esperada"],
            {"workflow": "consulta_direta", "intencao": "LOCAL_ONLY"},
        )
        # PDF + SGB combinam fontes mesmo sem termo de workflow.
        self.assertEqual(
            self.por_id["wf-pt-046"]["saida_esperada"],
            {"workflow": "consulta_direta", "intencao": "HIBRIDO"},
        )
        # Documentos + PDF + SGB + furo: workflow sondagem com HIBRIDO.
        self.assertEqual(
            self.por_id["wf-pt-047"]["saida_esperada"],
            {"workflow": "sondagem", "intencao": "HIBRIDO"},
        )
        # Manual de hidrogeologia não é termo SGB: documento sozinho.
        self.assertEqual(
            self.por_id["wf-pt-048"]["saida_esperada"],
            {"workflow": "hidrogeologia", "intencao": "LOCAL_ONLY"},
        )
        # Pedido fora de escopo com PDF não vira triagem nem HIBRIDO.
        self.assertEqual(
            self.por_id["wf-pt-050"]["saida_esperada"],
            {"workflow": "consulta_direta", "intencao": "LOCAL_ONLY"},
        )

    def test_gerador_nao_toca_no_banco_real(self):
        antes = _db_intocado.capturar()
        gerador.gerar_registros()
        depois = _db_intocado.capturar()
        self.assertTrue(
            _db_intocado.comparar(antes, depois)["DB_INTOCADO"]
        )


if __name__ == "__main__":
    unittest.main()
