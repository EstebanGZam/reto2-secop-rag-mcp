# Decisiones de diseño · Taller 02

## Alcance y contrato

Se integran las interfaces existentes de RAG, extracción, MCP y memoria sin cambiar la base compartida. Los veinte PDF son simulaciones educativas. El agente responde en español; código y prompts internos se escriben en inglés. La integración usa `get_chat_model`, `CostCounter`, la configuración y las funciones de embeddings comunes. No se pasan parámetros de muestreo.

## Fragmentación por sección

Las secciones numeradas representan unidades semánticas útiles: presupuesto, cronograma, experiencia y capacidad financiera. Se conserva la identidad del proceso, página inicial y título de sección. Fragmentos extensos se dividen a 1.200 caracteres con 120 de solapamiento; el corpus actual produce **157 fragmentos de 20 PDF**. Esto evita cortar arbitrariamente una condición financiera y permite citar una ubicación verificable. La página identifica el inicio del fragmento; no garantiza que todos sus caracteres estén en esa página.

## Filtrado por metadatos

Los documentos comparten estructura y vocabulario. La búsqueda puramente semántica puede confundir, por ejemplo, índices de liquidez de dos procesos. Antes del ranking se reconocen referencias, identificadores SECOP, nombres/números de archivo y entidades inequívocas. Se filtra el proceso y se quitan tokens de identidad al medir la relevancia del contenido. El parámetro `process` de la herramienta resuelve un archivo existente y no admite un filtro inventado. La lista de documentos solo constituye evidencia de identidades, no de requisitos.

## Umbral de recuperación

El retriever usa similitud coseno (80%) y cobertura de términos (20%), score mínimo **0,40** y cobertura mínima **0,60**. Coincidir exactamente con un título aporta una bonificación de **0,20**. Estos valores pertenecen al módulo RAG ya implementado. Una búsqueda sin candidatos suficientes devuelve `[]`, que la herramienta expone como `{"found": false}`.

El fixture de 24 preguntas se usó para calibrar estos valores. Los resultados posteriores describen ese fixture; no son una evaluación independiente. El filtro léxico puede perder paráfrasis válidas; la consulta enviada a la herramienta debe expresar el requisito buscado, separando datos personales e identidad del proceso. Un conjunto reservado, documentos nuevos y revisión humana son siguientes pasos para evaluar generalización.

## Embeddings, Chroma y LLM de chat

Son tres componentes distintos:

1. **Modelo de embeddings local:** sentence-transformers ejecuta `paraphrase-multilingual-MiniLM-L12-v2` para transformar texto en vectores multilingües. No redacta respuestas ni necesita Claude.
2. **ChromaDB:** persiste vectores, documentos y metadatos, y permite búsquedas por distancia y filtros. No genera embeddings por sí mismo: cuando recibe texto llama a la función de embeddings configurada. Corpus y memoria comparten esa función para evitar espacios incompatibles.
3. **LLM de chat:** interpreta la consulta, decide llamadas a herramientas y redacta. Se compara Claude Haiku 5.5 por API con `qwen2.5:3b` servido localmente por Ollama. Cambiar este LLM no reconstruye ni cambia los embeddings del índice.

## Frontera MCP

Las cuatro herramientas de contratación se sirven mediante FastMCP y el protocolo oficial por stdio. El agente las descubre con `MultiServerMCPClient`; no importa funciones de negocio directamente. El cliente del adaptador crea y cierra sus sesiones de subprocess por descubrimiento/llamada. La ejecución pasa `sys.executable`, el módulo `secop_mcp.server`, la raíz del proyecto y `MODO_DATOS`. Esto mantiene coherencia con el entorno `uv`.

RAG y memoria son funciones internas de la aplicación; MCP expone datos de procesos e indicadores empresariales para otros clientes, incluido Copilot. Cada respuesta MCP trae `source`. El modo muestra se usa para reproducibilidad; el modo API tiene dependencia externa y no se confunde con la muestra. La memoria MCP configurada para Copilot es independiente de la memoria del asistente Python.

## Citas y guard determinista

El prompt exige herramientas para hechos, respuestas en español y una etiqueta `[fuente: ...]` al final de cada frase factual. El texto documental, respuestas de herramientas, historial y memoria son datos; nunca se ejecutan sus instrucciones.

El guard acepta únicamente etiquetas exactas presentes en campos explícitos de las respuestas de herramientas del turno o `[fuente: memoria]` cuando hay contexto personal. No extrae supuestas fuentes de texto arbitrario dentro de un PDF. Rechaza etiquetas inventadas y cambios de página/sección. Si falta evidencia o una cita válida, devuelve `No lo sé: no encontré esa información en los documentos disponibles.`; conserva una abstención ya redactada.

**Límite:** es una comprobación de procedencia, no de implicación semántica. Las abstenciones se conservan textualmente; su explicación puede incluir etiquetas no verificadas, que no se incorporan a la lista de citas válidas. Una respuesta con una cita válida puede añadir afirmaciones no sustentadas; el guard no clasifica frases factuales ni garantiza una cita por frase. La instrucción de citar cada frase depende del LLM. La memoria tampoco debe considerarse autoridad documental. A/B compara el mismo prompt con y sin guard, sin cambiar el corpus o las herramientas.

## Niveles de memoria y olvido

Corto plazo: ventana de 10 mensajes y 8.000 caracteres, conservando intercambios completos. Medio plazo: resumen progresivo y sesiones persistentes con retención de 14 días; la sesión más reciente se incluye para dar continuidad incluso a preguntas vagas. Largo plazo: hechos personales atómicos, deduplicación por distancia 0,15 y puntuación por similitud (0,60), importancia (0,25) y recencia (0,15).

Cada usuario se filtra por `user_id`. `MemoryManager.build_context` se incorpora al prompt de cada turno; el historial corto precede la nueva pregunta. `record_turn` recibe la respuesta final ya revisada. Al cerrar se resumen mensajes y extraen hechos. Todas las llamadas usan el mismo LLM que el asistente, incluido Ollama cuando corresponde, y se cuentan.

`/olvida` delega en `MemoryManager.forget`: elimina hasta diez hechos cercanos con distancia menor que 0,30. **No borra resúmenes ni mensajes ya presentes** y puede eliminar hechos semánticamente próximos. La demo muestra un hecho antes y después, sin afirmar un borrado total. El contenido conservado puede volver a extraerse y restaurar un hecho al consolidar otra sesión. Los errores de consolidación se registran y la memoria funciona como mejor esfuerzo; un resumen puede ser inexacto. La demo vigente consolida y recuerda cuatro hechos personales; el primer turno compuesto ya responde con cita al PDF.

## Consultas breves y reintento antes de abstenerse

Antes del ajuste del prompt, enviar a búsqueda toda la presentación de Valeria junto con la pregunta de liquidez reducía la cobertura léxica por debajo de 0,60 y producía una falsa abstención. El lead modificó `SYSTEM_PROMPT` y la descripción de `search_tender_documents`: el modelo debe separar la referencia y enviar palabras clave breves del requisito; si no encuentra evidencia, reformula una vez antes de abstenerse. No se relajó el umbral del retriever.

Después del ajuste, la sesión 1 del notebook ejecutado responde «mayor o igual a 1.6» con `[fuente: 11_FDLS_LP_098_2019.pdf, p. 2, §5 Capacidad financiera y organizacional (según RUP)]`. La sesión 2 recupera nombre, ocupación, preferencia e interés desde memoria; su resumen conserva ahora el dato citado. La abstención anterior es un antecedente documentado, no el resultado de la demo vigente. Los casos negativos de §4 siguen absteniéndose. Esto verifica ese ejemplo compuesto, sin demostrar que toda paráfrasis o consulta compuesta funcionará. La [evidencia LangSmith](../resultados/evidencia_langsmith.md) enlaza la traza actual; no se presenta una traza antigua no conservada como prueba reproducible.

## Protocolo de evaluación

El fixture contiene 16 preguntas respondibles y 8 ausentes. Configuraciones: B-Claude con guard, A-Claude con prompt solamente, C-local con guard. Una pregunta equivale a una sesión aislada, con directorio temporal y `user_id` independiente, para que ningún caso aprenda de otro.

La corrección usa un juez Claude económico con salida estructurada y referencia del dataset; acepta equivalencia numérica/semántica. Es un juez automático, sin revisión humana ni garantía de imparcialidad. Una única muestra por pregunta no separa variación aleatoria de efecto del guard.

La precisión de fuente comprueba el PDF esperado en etiquetas (16 casos). Una respuesta correcta de MCP puede fallar esta métrica cuando el dataset exige el PDF. La abstención se calcula sobre los ocho casos ausentes; falsa abstención, sobre los dieciséis respondibles. Los errores operativos se cuentan como incorrectos y no como abstención acertada. Los fallos del juez quedan explícitos en JSON.

La extracción procesa veinte documentos, catorce campos cada uno. La clave se consulta solo al puntuar; coincidencia numérica con tolerancia absoluta 1e-6, booleanos estrictos, códigos sin orden y `None` con `None` válido. Campos o procesos ausentes cuentan como fallos. Esta medida es exactitud por campo, no precisión de clasificación positiva.

`CostCounter` cuenta llamadas del agente y de memoria, tokens, caché y USD según la tabla del proyecto. Se separan cierre de sesión y juez; la latencia por pregunta incluye recuperación y registro del turno, con cierre medido aparte. El coste de Ollama por token es cero, sin valorar hardware/energía. La extracción incluye recuperación y LLM en su tiempo total. Cada turno usa un UUID explícito como `run_id` del grafo para enlazar su traza LangSmith. Las llamadas de memoria y juez tienen sus propias trazas.

Los experimentos LangSmith suben las respuestas ya medidas para evitar duplicar gasto. Los checkpoints permiten reanudar sin repetir llamadas, y `--force` invalida deliberadamente esas mediciones. Tras cambiar implementación o protocolo hay que invalidar los checkpoints; no deben mezclarse versiones.

<!-- RESULTS:START -->
## Resultados y elección del modelo

| Configuración | Corrección | Fuente | Abstención (8) | Falsa abstención (16) | USD agente + memoria | USD juez | Latencia media s |
|---|---:|---:|---:|---:|---:|---:|---:|
| B-claude | 95.83% | 93.75% | 100.00% | 0.00% | 0.035452 | 0.003996 | 5.04 |
| A-claude | 91.67% | 81.25% | 87.50% | 6.25% | 0.036906 | 0.003826 | 5.16 |
| C-local | 33.33% | 0.00% | 100.00% | 87.50% | 0.000000 | 0.003683 | 2.23 |

Tokens entrada / salida (agente + memoria): B-claude **249,095 / 21,092** (80.58 s al cierre), A-claude **272,643 / 19,281** (71.98 s al cierre), C-local **60,580 / 3,759** (25.11 s al cierre). Los tiempos acumulados de consolidación al cierre quedan fuera de la media por turno.

Se recomienda **B-Claude** para esta entrega: obtuvo **23/24** respuestas correctas, 15/16 fuentes esperadas y ocho abstenciones correctas. Su único fallo, q05, comienza «Sí» y luego afirma «no se exige» la constitución de garantías: se conserva como respuesta contradictoria e incorrecta. A-Claude obtuvo **22/24**: q10 fue una falsa abstención y q20 agotó el límite de pasos con respuesta vacía. Una sola ejecución no demuestra una mejora causal del guard.

C-local obtuvo **8/24**, los ocho casos ausentes; falló los 16 respondibles, con 14 falsas abstenciones (87,50 %) y dos respuestas incorrectas sin el prefijo de abstención. Una calculó un porcentaje ajeno al requisito (q08); otra alegó falta de datos con cita MCP (q09). No acertó ninguna fuente PDF. Su latencia media de **2,23 s** y coste por token cero no compensan la calidad observada. Solo se evaluó Qwen 2.5 3B con este prompt y estas herramientas.

La discrepancia de fuente de B-Claude corresponde al perfil profesional de q06 respondido desde la muestra MCP en vez del PDF esperado. El guard valida procedencia, no coherencia semántica: q05 y las dos respuestas incorrectas locales citadas ilustran ese límite. El límite de pasos ocurre antes de aplicar el guard.

**Auditoría del juez:** la ejecución vigente conserva `judge_audits: []`; no se repitió un juicio para corregir contradicciones del evaluador. La revisión dirigida de C-local/q22 pertenecía a la ejecución anterior y no se atribuye a estos resultados.

**Extracción Claude: 279/280 campos (99,64 %), USD 0,009803**, 55.865 tokens de entrada, 8.435 de salida y 116,19 s. La extracción no se volvió a medir; se reutilizaron sus checkpoints. El desacuerdo sigue siendo `experience_by_similar_object` en `02_CD_55_2021_3516.pdf`. La extracción local adicional se omitió.

Los tres benchmarks, sus jueces y la extracción suman **USD 0.093666**, recomputados de los JSON vigentes (agente y memoria + juez + extracción). Las demos añaden llamadas y muestran sus costes por sesión. No es una factura conciliada ni el total histórico del proyecto LangSmith.

Evidencia: [RAG](../resultados/evaluacion_rag.md), [JSON RAG](../resultados/evaluacion_rag.json), [extracción](../resultados/extraccion_requisitos.md) y [mediciones LangSmith](../resultados/evidencia_langsmith.md). Los experimentos reutilizan respuestas medidas: sus costes/tokens pueden ser cero y su latencia refleja publicación. El informe de evidencia contrasta esas cifras con CostCounter y consulta las trazas originales, sin sumar raíces e hijos dos veces. Los jueces y la consolidación exterior al grafo tienen trazas separadas. LangSmith puede no disponer de precio para Ollama.
<!-- RESULTS:END -->
