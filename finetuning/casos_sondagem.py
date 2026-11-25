"""Casos da tarefa de extração estruturada de sondagem.

Cada tabela é uma entrada real do parser De-Até: vírgula ou ponto
decimal, metros ou centímetros, coluna Unidade, célula Intervalo,
cabeçalho com unidade, linhas incompletas e casos negativos. O gabarito
vem de services.sondagem.analisar_sondagem.
"""

from __future__ import annotations

CASOS_SONDAGEM = [
    {
        "familia": "normal",
        "pt": (
            "Furo;De;Até;Unidade;Litologia\n"
            "FQ-01;0,00;2,50;m;Areia fina"
        ),
        "en": (
            "Hole;From;To;Unit;Lithology\n"
            "BH-01;0.00;2.50;m;Fine sand"
        ),
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-02;2,5;5,0;Saprolito",
        "en": "Hole;From;To;Lithology\nBH-02;2.5;5.0;Saprolite",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Unidade;Litologia\nFQ-03;0;150;cm;Solo coluvial",
        "en": "Hole;From;To;Unit;Lithology\nBH-03;0;150;cm;Colluvial soil",
    },
    {
        "familia": "normal",
        "pt": "Furo;Intervalo;Litologia\nFQ-04;0 - 2,5 m;Rocha alterada",
        "en": "Hole;Interval;Lithology\nBH-04;0 - 2.5 m;Weathered rock",
    },
    {
        "familia": "normal",
        "pt": "Furo;Intervalo;Litologia\nFQ-05;0 - 150 cm;Saprolito",
        "en": "Hole;Interval;Lithology\nBH-05;0 - 150 cm;Saprolite",
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;Prof. de (cm);Prof. até (cm);Litologia\n"
            "FQ-06;0;150;Solo"
        ),
        "en": (
            "Hole;From (cm);To (cm);Lithology\n"
            "BH-06;0;150;Soil"
        ),
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-07;0 m;150 cm;Contato",
        "en": "Hole;From;To;Lithology\nBH-07;0 m;150 cm;Contact",
    },
    {
        "familia": "normal",
        "pt": "Furo;Intervalo;Litologia\nFQ-08;0 até 2,5 m;Rocha",
        "en": "Hole;Interval;Lithology\nBH-08;0 to 2.5 m;Rock",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-09;0.5;1.25;Areia",
        "en": "Hole;From;To;Lithology\nBH-09;0.5;1.25;Sand",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-10;0,5;1,25;Areia",
        "en": "Hole;From;To;Lithology\nBH-10;0,5;1,25;Sand",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-12;-0;2,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-12;-0;2.5;Soil",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-13;0;150cm;Saprolito",
        "en": "Hole;From;To;Lithology\nBH-13;0;150cm;Saprolite",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Unidade;Litologia\nFQ-14;0;150;centímetros;Solo",
        "en": "Hole;From;To;Unit;Lithology\nBH-14;0;150;centimeters;Soil",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-15;0;2,5;Areia fina, quartzosa",
        "en": "Hole;From;To;Lithology\nBH-15;0;2.5;Fine sand, quartzose",
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;De;Até;Unidade;Litologia;Amostra;Observação\n"
            "FQ-16;1,0;2,0;m;Silte;A-16;Contato nítido"
        ),
        "en": (
            "Hole;From;To;Unit;Lithology;Sample;Remarks\n"
            "BH-16;1.0;2.0;m;Silt;S-16;Sharp contact"
        ),
    },
    {
        "familia": "normal",
        "pt": "Furo;Intervalo;Unidade;Litologia\nFQ-17;0 - 150;cm;Saprolito",
        "en": "Hole;Interval;Unit;Lithology\nBH-17;0 - 150;cm;Saprolite",
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;Profundidade de;Profundidade até;Litologia\n"
            "FQ-18;0,2;1,7;Silte arenoso"
        ),
        "en": (
            "Hole;Depth From;Depth To;Lithology\n"
            "BH-18;0.2;1.7;Sandy silt"
        ),
    },
    {
        "familia": "ambiguo",
        "pt": "Furo;De;Até;Litologia\nFQ-11;1.234,5;1.235,0;Rocha",
        "en": "Hole;From;To;Lithology\nBH-11;1,234.5;1,235.0;Rock",
    },
    {
        "familia": "ambiguo",
        "pt": "Furo;De;Até;Litologia\nFQ-19;0;2,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-19;0;2.5;Soil",
    },
    {
        "familia": "ambiguo",
        "pt": "Furo;De;Até;Litologia\nFQ-20;0 m;2,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-20;0 m;2.5;Soil",
    },
    {
        "familia": "ambiguo",
        "pt": "Furo;Intervalo;Litologia\nFQ-21;0 cm - 150 cm;Saprolito",
        "en": "Hole;Interval;Lithology\nBH-21;0 cm - 150 cm;Saprolite",
    },
    {
        "familia": "ambiguo",
        "pt": "Furo;De;Até;Litologia\nFQ-22;1.234;1.235;Rocha",
        "en": "Hole;From;To;Lithology\nBH-22;1.234;1.235;Rock",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia\n;0;2,5;Solo",
        "en": "Hole;From;To;Lithology\n;0;2.5;Soil",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia\nFQ-24;;2,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-24;;2.5;Soil",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia\nFQ-25;0;;Solo",
        "en": "Hole;From;To;Lithology\nBH-25;0;;Soil",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;Litologia\nFQ-26;Solo",
        "en": "Hole;Lithology\nBH-26;Soil",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia",
        "en": "Hole;From;To;Lithology",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia\n;;2,5;Solo",
        "en": "Hole;From;To;Lithology\n;;2.5;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-28;2,5;0,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-28;2.5;0.5;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-29;-1;2;Solo",
        "en": "Hole;From;To;Lithology\nBH-29;-1;2;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-30;abc;2;Solo",
        "en": "Hole;From;To;Lithology\nBH-30;abc;2;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Unidade;Litologia\nFQ-31;0;2;milhas;Solo",
        "en": "Hole;From;To;Unit;Lithology\nBH-31;0;2;miles;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-32;0;2;Solo;extra",
        "en": "Hole;From;To;Lithology\nBH-32;0;2;Soil;extra",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-33;0;xyz;Solo",
        "en": "Hole;From;To;Lithology\nBH-33;0;xyz;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-34;1,2,3;2;Solo",
        "en": "Hole;From;To;Lithology\nBH-34;1,2,3;2;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-35;0;-2;Solo",
        "en": "Hole;From;To;Lithology\nBH-35;0;-2;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;Intervalo;Litologia\nFQ-36;2,5 - 0;Solo",
        "en": "Hole;Interval;Lithology\nBH-36;2.5 - 0;Soil",
    },

    # ------------------------------------------------------------------
    # Casos v2: erros residuais do benchmark qwen3:4b (consolidado v2).
    # Cobrem unidade implicita, conversao cm -> m, separador de milhar,
    # sinal/invalido sem inventar numero, erro_contrato versus linha
    # invalida e tabelas com varios intervalos (sobreposicao e lacuna).
    # ------------------------------------------------------------------
    {
        "familia": "normal",
        "pt": (
            "Furo;Prof. de (m);Prof. até (m);Litologia\n"
            "FQ-37;0;3,75;Silte arenoso"
        ),
        "en": (
            "Hole;From (m);To (m);Lithology\n"
            "BH-37;0;3.75;Sandy silt"
        ),
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-38;0;10;Rocha",
        "en": "Hole;From;To;Lithology\nBH-38;0;10;Rock",
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Unidade;Litologia\nFQ-39;0;250;cm;Argila",
        "en": "Hole;From;To;Unit;Lithology\nBH-39;0;250;cm;Clay",
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;Prof. de (cm);Prof. até (cm);Litologia\n"
            "FQ-40;100;250;Areia média"
        ),
        "en": (
            "Hole;From (cm);To (cm);Lithology\n"
            "BH-40;100;250;Medium sand"
        ),
    },
    {
        "familia": "normal",
        "pt": "Furo;De;Até;Litologia\nFQ-41;0 m;250 cm;Contato",
        "en": "Hole;From;To;Lithology\nBH-41;0 m;250 cm;Contact",
    },
    {
        "familia": "normal",
        "pt": "Furo;Intervalo;Litologia\nFQ-42;0 até 2,75 m;Rocha alterada",
        "en": "Hole;Interval;Lithology\nBH-42;0 to 2.75 m;Weathered rock",
    },
    {
        "familia": "ambiguo",
        "pt": (
            "Furo;De;Até;Litologia\n"
            "FQ-43;12.345,6;12.346,0;Rocha"
        ),
        "en": (
            "Hole;From;To;Lithology\n"
            "BH-43;12,345.6;12,346.0;Rock"
        ),
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-44;-0,5;1,5;Solo",
        "en": "Hole;From;To;Lithology\nBH-44;-0.5;1.5;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-45;1.234.567;2;Solo",
        "en": "Hole;From;To;Lithology\nBH-45;1,234,567;2;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Unidade;Litologia\nFQ-46;0;2;jardas;Solo",
        "en": "Hole;From;To;Unit;Lithology\nBH-46;0;2;yards;Soil",
    },
    {
        "familia": "negativo",
        "pt": "Furo;De;Até;Litologia\nFQ-47;0;0;Contato",
        "en": "Hole;From;To;Lithology\nBH-47;0;0;Contact",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Litologia\nFQ-48;0;Solo",
        "en": "Hole;From;Lithology\nBH-48;0;Soil",
    },
    {
        "familia": "incompleto",
        "pt": "Furo;De;Até;Litologia\nFQ-49;0;2;Solo;extra",
        "en": "Hole;From;To;Lithology\nBH-49;0;2;Soil;extra",
    },
    {
        "familia": "ambiguo",
        "pt": (
            "Furo;De;Até;Litologia\n"
            "FQ-50;2;4;Rocha\n"
            "FQ-50;0;3;Solo"
        ),
        "en": (
            "Hole;From;To;Lithology\n"
            "BH-50;2;4;Rock\n"
            "BH-50;0;3;Soil"
        ),
    },
    {
        "familia": "ambiguo",
        "pt": (
            "Furo;De;Até;Litologia\n"
            "FQ-51;5;6;Rocha\n"
            "FQ-51;0;4,5;Solo"
        ),
        "en": (
            "Hole;From;To;Lithology\n"
            "BH-51;5;6;Rock\n"
            "BH-51;0;4.5;Soil"
        ),
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;De;Até;Litologia\n"
            "FQ-52;0;2,5;Solo\n"
            "FQ-52;2,5;5;Rocha"
        ),
        "en": (
            "Hole;From;To;Lithology\n"
            "BH-52;0;2.5;Soil\n"
            "BH-52;2.5;5;Rock"
        ),
    },
    {
        "familia": "normal",
        "pt": (
            "Furo;De;Até;Litologia\n"
            "FQ-53;0;1;Solo\n"
            "FQ-54;0;2;Rocha"
        ),
        "en": (
            "Hole;From;To;Lithology\n"
            "BH-53;0;1;Soil\n"
            "BH-54;0;2;Rock"
        ),
    },
]
