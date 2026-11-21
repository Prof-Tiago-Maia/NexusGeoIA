"""Testes de guarda da suite de auditoria de release.

Estes testes garantem que os proprios instrumentos de QA continuam
existindo, documentados e sintaticamente validos. Eles nao executam o
`.exe` nem acessam a rede.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PACKAGING = RAIZ / "packaging"
SKILL = RAIZ / ".claude" / "skills" / "qa-windows-release" / "SKILL.md"


def ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8")


class TestAuditoriaCleanRoom(unittest.TestCase):
    """O script PowerShell cobre as barreiras obrigatorias do release."""

    def test_script_existe_e_tem_as_checagens_obrigatorias(self):
        caminho = PACKAGING / "auditoria_clean_room.ps1"
        self.assertTrue(caminho.is_file())
        codigo = ler(caminho)

        for trecho in (
            "NexusGeoIA_CleanRoom_Test",
            "_internal\\certifi\\cacert.pem",
            ".streamlit\\config.toml",
            "prompts\\system_base.txt",
            "iniciar.bat",
            "--autoteste",
            "WaitForExit",
            "Start-Sleep -Seconds 3",
            'Get-Process -Name "NexusGeoIA"',
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "RESULTADO: PASS",
            "RESULTADO: FAIL",
            "Recusando remover caminho fora",
        ):
            self.assertIn(trecho, codigo)

    def test_script_nao_confia_em_path_com_venv(self):
        codigo = ler(PACKAGING / "auditoria_clean_room.ps1")

        self.assertIn("\\.venv", codigo)
        self.assertIn("VIRTUAL_ENV", codigo)
        self.assertIn("PYTHONHOME", codigo)
        self.assertIn("PYTHONPATH", codigo)
        self.assertIn("CONDA_PREFIX", codigo)

    def test_script_passa_no_parser_do_powershell(self):
        interpretador = None

        for nome in ("pwsh", "powershell"):
            caminho = shutil.which(nome)

            if caminho:
                interpretador = caminho
                break

        if not interpretador:
            self.skipTest("PowerShell indisponivel para validar sintaxe")

        script = PACKAGING / "auditoria_clean_room.ps1"
        comando = (
            "$erros = $null; $tokens = $null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$tokens, [ref]$erros) | Out-Null; "
            "if ($erros.Count -gt 0) { "
            "$erros | ForEach-Object { Write-Output $_.Message }; exit 1 "
            "} else { exit 0 }"
        )

        resultado = subprocess.run(
            [
                interpretador,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                comando,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(
            resultado.returncode,
            0,
            f"auditoria_clean_room.ps1 tem erro de sintaxe: "
            f"{resultado.stdout} {resultado.stderr}",
        )


class TestAuditoriaEstatica(unittest.TestCase):
    """A analise estatica permanente aprova o repositorio."""

    def test_script_compila_e_detecta_ciclos(self):
        caminho = PACKAGING / "auditoria_estatica.py"
        self.assertTrue(caminho.is_file())
        codigo = ler(caminho)

        for trecho in (
            "compilar(",
            "detectar_ciclos(",
            "imports_quebrados",
            "py_compile",
        ):
            self.assertIn(trecho, codigo)

    def test_repositorio_passa_na_auditoria_estatica(self):
        resultado = subprocess.run(
            [
                sys.executable,
                str(PACKAGING / "auditoria_estatica.py"),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=RAIZ,
        )

        self.assertEqual(
            resultado.returncode,
            0,
            f"auditoria estatica reprovou: {resultado.stderr}",
        )

        relatorio = json.loads(resultado.stdout)

        self.assertTrue(relatorio["ok"])
        self.assertEqual(relatorio["falhas_compilacao"], [])
        self.assertEqual(relatorio["imports_quebrados"], [])
        self.assertEqual(relatorio["ciclos"], [])


class TestSkillQaWindowsRelease(unittest.TestCase):
    """A skill reutilizavel documenta o protocolo completo."""

    def test_skill_existe_com_frontmatter(self):
        self.assertTrue(SKILL.is_file())
        texto = ler(SKILL)

        self.assertTrue(texto.startswith("---"))
        self.assertIn("name: qa-windows-release", texto)
        self.assertIn("description:", texto)

    def test_skill_documenta_as_tres_etapas_obrigatorias(self):
        texto = ler(SKILL)

        for trecho in (
            "auditoria_estatica.py",
            "py_compile",
            "ruff.exe check",
            "unittest discover -s tests",
            "auditoria_clean_room.ps1",
            "git tag",
            "GitHub Release",
            "SSL_CERT_FILE",
            "certifi",
        ):
            self.assertIn(trecho, texto)

    def test_skill_proibe_atalhos_perigosos(self):
        texto = ler(SKILL)

        self.assertIn("Atalhos proibidos", texto)
        self.assertIn("RESULTADO: FAIL", texto)
        self.assertIn("processo órfão", texto.lower())


if __name__ == "__main__":
    unittest.main()
