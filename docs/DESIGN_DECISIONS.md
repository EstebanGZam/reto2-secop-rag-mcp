# Decisiones de diseño · Taller 02

## Alcance y contrato

Se integran las interfaces existentes de RAG, extracción, MCP y memoria sin cambiar la base compartida. Los veinte PDF son simulaciones educativas. El agente responde en español; código y prompts internos se escriben en inglés. La integración usa `get_chat_model`, `CostCounter`, la configuración y las funciones de embeddings comunes. No se pasan parámetros de muestreo.

## Fragmentación por sección

Las secciones numeradas representan unidades semánticas útiles: presupuesto, cronograma, experiencia y capacidad financiera. Se conserva la identidad del proceso, página inicial y título de sección. Fragmentos extensos se dividen a 1.200 caracteres con 120 de solapamiento; el corpus actual produce **157 fragmentos de 20 PDF**. Esto evita cortar arbitrariamente una condición financiera y permite citar una ubicación verificable. La página identifica el inicio del fragmento; no garantiza que todos sus caracteres estén en esa página.

## Filtrado por metadatos

Los documentos comparten estructura y vocabulario. La búsqueda puramente semántica puede confundir, por ejemplo, índices de liquidez de dos procesos. Antes del ranking se reconocen referencias, identificadores SECOP, nombres/números de archivo y entidades inequívocas. Se filtra el proceso y se quitan tokens de identidad al medir la relevancia del contenido. El parámetro `process` de la herramienta resuelve un archivo existente y no admite un filtro inventado. La lista de documentos solo constituye evidencia de identidades, no de requisitos.

## Umbral de recuperación

El retriever usa similitud coseno (80%) y cobertura de términos (20%), score mínimo **0,40** y cobertura mínima **0,60**. Coincidir exactamente con un título aporta una bonificación de **0,20**. Estos valores pertenecen al módulo RAG ya implementado. Una búsqueda sin candidatos suficientes devuelve `[]`, que la herramienta expone como `{"found": false}`.

El fixture de 24 preguntas se usó para calibrar estos valores. Los resultados posteriores describen ese fixture; no son una evaluación independiente. El filtro léxico puede perder paráfrasis válidas y rechazar preguntas compuestas. Un conjunto reservado, documentos nuevos y revisión humana son siguientes pasos para evaluar generalización.

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

`/olvida` delega en `MemoryManager.forget`: elimina hasta diez hechos cercanos con distancia menor que 0,30. **No borra resúmenes ni mensajes ya presentes** y puede eliminar hechos semánticamente próximos. La demo muestra un hecho antes y después, sin afirmar un borrado total. El contenido conservado puede volver a extraerse y restaurar un hecho al consolidar otra sesión. Los errores de consolidación se registran y la memoria funciona como mejor esfuerzo; un resumen puede ser inexacto. En la demo guardada, el primer turno compuesto (presentación personal + pregunta de liquidez) produjo una abstención pese a existir el dato. Los cuatro hechos personales sí se consolidaron y recordaron en la segunda instancia, pero el resumen también retuvo esa respuesta fallida. El fixture de preguntas simples no cubre ese tipo de consulta compuesta.

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
| B-claude | 100.00% | 93.75% | 100.00% | 0.00% | 0.033999 | 0.003809 | 6.34 |
| A-claude | 95.83% | 93.75% | 87.50% | 0.00% | 0.038767 | 0.003642 | 5.81 |
| C-local | 33.33% | 0.00% | 100.00% | 93.75% | 0.000000 | 0.003493 | 1.25 |

Tokens totales de entrada/salida (agente + memoria): B-Claude **244.137 / 19.178**, A-Claude **284.611 / 20.616**, C-local **49.277 / 2.115**. La consolidación al cierre añadió, respectivamente, 83,87 s, 81,75 s y 18,79 s acumulados en las 24 sesiones; está fuera de la media por turno de la tabla.

**Recomendación: Claude Haiku 5.5 con guard**, por la calidad observada y el gasto reducido. B-Claude acertó 24/24 según el juez, con 15/16 fuentes esperadas y ocho abstenciones correctas. La discrepancia de fuente fue una respuesta de presupuesto basada en la muestra MCP, mientras el fixture exigía el PDF. A-Claude alcanzó el límite de 16 pasos en q20: una pregunta sin multa diaria desencadenó llamadas repetidas. Ese error explica 23/24 de corrección y 7/8 abstenciones; no prueba por sí solo una mejora causal del guard, que se aplica después de terminar el grafo.

C-local acertó 8/24: los ocho casos ausentes. En los respondibles, hubo 15 abstenciones con el prefijo requerido (93,75%) y otra respuesta que alegaba ausencia sin ese prefijo. Esa última respuesta pasó la validación de procedencia con una cita MCP, aunque no respondía el requisito documental: ejemplo del límite semántico del guard. No hubo fuente PDF acertada. Su latencia de 1,25 s y precio por token cero no compensan esa calidad para la entrega. No se concluye que todos los modelos locales fallen: solo se midió Qwen 2.5 3B con este prompt y estas herramientas, sin ajuste específico.

**Auditoría del juez:** la respuesta C-local/q22 fue «No lo sé.»; inicialmente el juez devolvió `correct=false` aunque su explicación afirmaba que debía ser correcto. Se hizo un único segundo juicio, aclarando que la respondibilidad es respecto al corpus, no al conocimiento general. Devolvió `true`. El JSON guarda `judge_initial`, la explicación, el coste original y el segundo coste acumulado; no se repitió el agente. Esta revisión dirigida impide considerar el benchmark completamente automático. Las demás puntuaciones no se revisaron manualmente.

La extracción Claude obtuvo **279/280 campos = 99,64%**, en 20 llamadas, con 55.865 tokens de entrada, 8.435 de salida, 116,19 s y **USD 0,009803**. El desacuerdo fue `experience_by_similar_object` en `02_CD_55_2021_3516.pdf`. Se conserva el error sin adaptar el extractor a la clave. La extracción local opcional se omitió para acotar el tiempo de entrega; la comparación local sí se ejecutó completa para las 24 preguntas del agente.

Los tres benchmarks de preguntas, sus jueces (incluida la revisión) y la extracción suman **USD 0,093513** según la tabla del proyecto; las demostraciones del notebook añaden sus propias llamadas y muestran su coste por sesión. No es una factura verificada del proveedor.

Evidencia: [RAG](../resultados/evaluacion_rag.md), [JSON RAG](../resultados/evaluacion_rag.json), [extracción](../resultados/extraccion_requisitos.md) y [proyecto LangSmith](https://smith.langchain.com/o/be862a28-1dbf-4dec-b6c4-f58119a8f835/projects/p/6f480c7b-d861-4a8b-af41-8211bf4a1efc). Una traza original se verificó leyendo su UUID y comprobando su correspondencia con `run_id`.
<!-- RESULTS:END -->
