# Engenharia de Segurança para Sistemas de IA

Materiais dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta a **Parte VII, capítulos 25–28**, preservando as anteriores. Estão redigidos os capítulos 1–28 dos 36 previstos. Comece pelo [roteiro da Parte VII](PARTE_VII.md). Permanecem disponíveis [Parte VI](PARTE_VI.md), [Parte V](PARTE_V.md), [Parte IV](PARTE_IV.md), [Parte III](PARTE_III.md), [Parte II](PARTE_II.md), [Parte I](PARTE_I.md) e [L00/M1](COMECE_AQUI.md).

| Laboratório | Evidência nova |
|---|---|
| L25 | Ataque de pertencimento, três ajustes diffprivlib e contador de orçamento |
| L26 | GRU própria, quatro treinamentos, 2.000 passos, adaptação total e baixo posto |
| L27 | Dois perfis Docker, rede, TLS, identidade, cache por tenant e cota |
| L28 | Três imagens, gates, quatro smokes HTTP e reversão observada |

O pacote cumulativo passou em **370 testes**, sendo 43 novos, e **62 trabalhos de teste/reconciliação**. A Parte VII foi executada duas vezes no mesmo computador: referência `output/parte7_v01` e repetição `output/parte7_qualificacao_v01`. A suíte nova testa componentes e contraprovas; as duas capturas registram os treinamentos e deployments completos. Reconciliar capturas antigas não equivale a repetir todos os runtimes anteriores.

Use o ambiente isolado descrito no roteiro. O diffprivlib 0.6.6 precisou de scikit-learn 1.5.2 e SciPy 1.15.3 nesta qualificação; o ambiente anterior não foi substituído. A versão de PyTorch CPU é fixada em arquivo separado. L27/L28 exigem Docker e uma imagem-base por digest. Sem GPU, API paga, LLM pré-treinado ou dados reais confidenciais.

Os 689 arquivos históricos, além de README e manifesto geral, permanecem byte a byte. Esses dois documentos conservam sua história no Git. O pacote inclui código, testes, guias, locks, capturas, pequenos modelos próprios em JSON e bundles de código dos exercícios. Livro, PDF, EPUB, fontes, capas, KDP, pesos de LLM, executáveis e chaves TLS ficam fora.

`run` cria nova evidência; `verify` reconcilia a captura. Não use `python -O`, não sobrescreva resultados e não recalcule hashes históricos para esconder divergências. O pacote sintético inteiro não tem uma garantia DP de dados privados. A GRU não demonstra segurança de LLMs em linguagem natural. A implantação é local, com controlador confiável e sem CI remota. Reprodução independente e revisão do autor permanecem pendentes.
