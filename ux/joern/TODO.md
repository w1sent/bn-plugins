# joern — Code Property Graph analysis for Binary Ninja

## Scope
- [ ] Construct a Code Property Graph (CPG) from BN's lifted IL
- [ ] CPG combines: AST, CFG, data flow, control dependencies into a single graph
- [ ] Query the CPG to find patterns: vulnerabilities, crypto routines, protocol parsers
- [ ] Pattern library: pre-built queries for common RE tasks
- [ ] Match against known vulnerability signatures (CWE patterns)
- [ ] Either based on Joern (subprocess) or own CPG implementation with similar scope

## Architecture
- [ ] Option A: Joern-based — export BNIL to Joern's import format, run joern CLI as subprocess
- [ ] Option B: Own CPG — build CPG in-process from BNIL, implement query engine natively
- [ ] Decision deferred: evaluate Joern integration complexity vs. own implementation scope
- [ ] If Joern-based: requires Joern installation (Java/Scala), subprocess communication
- [ ] If own: pure Python, no external deps beyond BN API, but significant implementation effort

## CPG construction
- [ ] AST nodes: HLIL instructions as tree nodes
- [ ] CFG edges: control flow between basic blocks
- [ ] Data flow edges: def-use chains for variables and registers
- [ ] Control dependence edges: which branches control which statements
- [ ] Call edges: function call relationships
- [ ] Type edges: type information attached to nodes
- [ ] Source/sink annotations: identify input sources and output sinks

## Query language
- [ ] If Joern-based: CPGQL (Joern's Scala-based query DSL)
- [ ] If own: Python-based query API or a simplified pattern-matching DSL
- [ ] Common query patterns:
  - "Find all paths from source X to sink Y"
  - "Find functions that call both malloc and free"
  - "Find unchecked buffer accesses"
  - "Find crypto constants (AES, SHA, etc.)"
  - "Find format string vulnerabilities"
  - "Find use-after-free patterns"

## Pattern library
- [ ] Crypto detection: AES, DES, SHA, MD5, CRC constants and structures
- [ ] Memory corruption: buffer overflows, format strings, use-after-free, double-free
- [ ] Injection: command injection, SQL injection, path traversal
- [ ] Information disclosure: logging sensitive data, unchecked error paths
- [ ] Anti-analysis: anti-debug, anti-VM, obfuscation patterns
- [ ] Protocol parsing: length-delimited parsers, state machines
- [ ] Authentication: password checks, token validation, key derivation

## Commands
- [ ] "Build CPG" — constructs the CPG for the current binary
- [ ] "Query CPG" — opens a query input dialog, runs query, shows results
- [ ] "Run Pattern" — select from pattern library, run against CPG, show matches
- [ ] "Find Paths" — find all paths between selected source and sink
- [ ] "Show in CPG View" — opens a graph view of the CPG (subset around match)

## UI
- [ ] CPG view: interactive graph showing matched nodes and edges
- [ ] Query results: table of matches with jump-to-address links
- [ ] Pattern browser: categorized list of pre-built patterns with descriptions
- [ ] Source/sink highlighter: highlight sources and sinks in disassembly
- [ ] Progress bar during CPG construction (can be slow for large binaries)

## API (`api.py`)
- [ ] `build_cpg(bv) -> CPG`
- [ ] `query(cpg, query_string) -> list[QueryResult]`
- [ ] `run_pattern(cpg, pattern_name) -> list[QueryResult]`
- [ ] `find_paths(cpg, source_addr, sink_addr) -> list[Path]`
- [ ] `get_sources(cpg) -> list[Source]`
- [ ] `get_sinks(cpg) -> list[Sink]`
- [ ] `api.help()`
- [ ] All functions fully type-hinted

### Types
- [ ] `CPG(nodes: list[CPGNode], edges: list[CPGEdge])`
- [ ] `CPGNode(id: str, kind: str, address: int, properties: dict)`
- [ ] `CPGEdge(source: str, target: str, kind: str)`
- [ ] `QueryResult(matches: list[CPGNode], description: str)`
- [ ] `Path(nodes: list[CPGNode], edges: list[CPGEdge], score: float)`

## Settings (BN native)
- [ ] `joern.backend` (enum: `"native"` / `"joern"`, default `"native"`) — which CPG backend to use
- [ ] `joern.joern_path` (string, default `""`) — path to joern CLI; empty = use PATH
- [ ] `joern.auto_build` (bool, default `false`) — auto-build CPG on binary open

## Integration
- [ ] node-canvas: display CPG subgraphs in node-canvas
- [ ] relevance: CPG queries can inform relevance analysis (e.g. "find all crypto" → tag as relevant)
- [ ] chat: agent can query CPG via tools

## Notes
- Joern: https://joern.io — open-source CPG platform, Scala-based, supports C/C++ but not native binary
- For binary analysis, Joern would need a BNIL→C pseudocode export or a custom CPG frontend
- Own CPG implementation gives full control over BNIL integration but is a large undertaking
- Consider: incremental CPG — build lazily for queried functions, not whole binary at once
- Consider: CPG serialization — cache built CPG in BN's analysis database
- CPG is a powerful foundation: many other plugins (relevance, suggest-structs) could leverage it
