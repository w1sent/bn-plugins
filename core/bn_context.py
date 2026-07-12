def get_function_context(bv, func):
    lines = []
    for block in func.llil:
        if block is None:
            continue
        for instr in block:
            lines.append(f"  {instr.address:#x}: {instr}")
    return {
        "name": func.name,
        "address": func.start,
        "symbol": func.symbol.name if func.symbol else "",
        "disassembly": "\n".join(lines),
    }


def get_symbol_table(bv):
    symbols = []
    for name, syms in bv.symbols.items():
        for sym in syms:
            symbols.append(
                {
                    "name": name,
                    "address": sym.address,
                    "type": str(sym.type),
                }
            )
    return symbols


def get_call_graph(bv, func):
    callers = [f.name for f in func.callers]
    callees = [f.name for f in func.callees]
    return {"callers": callers, "callees": callees}


def get_data_references(bv, addr):
    refs = []
    for ref in bv.get_data_refs(addr):
        refs.append({"address": ref, "type": "data_ref"})
    return refs
