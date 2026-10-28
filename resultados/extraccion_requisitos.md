# Extracción de requisitos

20 PDF simulados × 14 campos = 280 comparaciones. Tolerancia numérica absoluta: 1e-6; listas sin orden; ausentes cuentan como error.

| Modelo | Aciertos | Total | Exactitud | USD | Tokens entrada | Tokens salida | Tiempo s |
|---|---:|---:|---:|---:|---:|---:|---:|
| anthropic:claude-haiku-5-5 | 279 | 280 | 99.6% | 0.009803 | 55865 | 8435 | 116.19 |

## anthropic:claude-haiku-5-5

| Campo | Aciertos / 20 | Exactitud |
|---|---:|---:|
| is_direct_contracting | 20 / 20 | 100.0% |
| is_sale_of_goods | 20 / 20 | 100.0% |
| verifies_financial_capacity | 20 / 20 | 100.0% |
| min_liquidity | 20 / 20 | 100.0% |
| max_debt_ratio_pct | 20 / 20 | 100.0% |
| min_interest_coverage | 20 / 20 | 100.0% |
| min_working_capital_budget_pct | 20 / 20 | 100.0% |
| min_return_on_equity | 20 / 20 | 100.0% |
| min_return_on_assets | 20 / 20 | 100.0% |
| experience_unspsc_codes | 20 / 20 | 100.0% |
| experience_by_similar_object | 19 / 20 | 95.0% |
| max_experience_contracts | 20 / 20 | 100.0% |
| experience_budget_pct | 20 / 20 | 100.0% |
| min_single_contract_budget_pct | 20 / 20 | 100.0% |

| PDF | Aciertos / 14 |
|---|---:|
| 01_EDP_545_2022.pdf | 14 / 14 |
| 02_CD_55_2021_3516.pdf | 13 / 14 |
| 03_RE_CGBM_049_2024.pdf | 14 / 14 |
| 04_CD_CPS_0720_2026.pdf | 14 / 14 |
| 05_PS_147_2025.pdf | 14 / 14 |
| 06_SINF_CPS_050_23.pdf | 14 / 14 |
| 07_135116.pdf | 14 / 14 |
| 08_OC10_2494_2025.pdf | 14 / 14 |
| 09_SDIS_CPS_302405_2024.pdf | 14 / 14 |
| 10_009_2021.pdf | 14 / 14 |
| 11_FDLS_LP_098_2019.pdf | 14 / 14 |
| 12_FNV_001_2021.pdf | 14 / 14 |
| 13_LP_DT_CAU_003_2019.pdf | 14 / 14 |
| 14_FLO_INFRA_SA_MC_007_2025.pdf | 14 / 14 |
| 15_SA_004_2023.pdf | 14 / 14 |
| 16_CD_PS_GDCH_186SS_2024.pdf | 14 / 14 |
| 17_5308_SASP01_2023.pdf | 14 / 14 |
| 18_0511_2024.pdf | 14 / 14 |
| 19_CSS_297_2024.pdf | 14 / 14 |
| 20_CPS_009_2026.pdf | 14 / 14 |

Extracción local: Skipped: optional local extraction deferred to keep runtime bounded.

Coste según la tabla del proyecto. No se consulta la clave durante la extracción.
