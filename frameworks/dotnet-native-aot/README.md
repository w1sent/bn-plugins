# .NET NativeAOT

Recovers .NET NativeAOT runtime metadata in compiled binaries: the
MethodTable/EEType type hierarchy, virtual method names, and frozen
strings/arrays/boxed values -- all without IL, a CLR, or symbols.

NativeAOT binaries compile fully to native code (no JIT, no IL left at
runtime) but retain a stripped-down ReadyToRun (RTR) directory pointing at
the runtime's own type descriptors. This plugin locates that directory,
decodes it, and walks the induced C++-vtable-like inheritance graph
outward from `System.Object` to recover as much of the original type system
as the binary still carries.

Python port of [washi1337/ghidra-nativeaot](https://github.com/washi1337/ghidra-nativeaot)
(see the [write-up](https://blog.washi.dev/posts/recovering-nativeaot-metadata/)),
cross-checked against its IDA port.

## Commands

| Command | Context | Description |
|---|---|---|
| NativeAOT \| Recover Metadata | Toolbar / Command palette | Locate all RTR modules and run full recovery. Only shown when a ReadyToRun directory is actually detected (see `auto_detect_rtr` below). |
| NativeAOT \| Recover Metadata (Force) | Toolbar / Command palette | Same command, always shown on 64-bit binaries -- use this if auto-detection missed a real NativeAOT binary. |

Recovery runs on a background thread (the whole-binary pointer scan/crawl
can take a while); Binary Ninja stays responsive. A tag (`NativeAOT
Recovered`, one per module header) and a log summary (counts + warnings)
are left when it finishes.

## What it does

1. **Locates the ReadyToRun directory** -- first by symbol (`__ReadyToRunHeader`,
   or the `__modules_a`/`__modules_z` array the native entry point passes to
   `StartupCodeHelpers.InitializeModules`), falling back to a signature
   scan (`RTR\0` + plausible section count/entry-size/entry-type) over
   non-executable data segments.
2. **Rehydrates the compressed metadata** (.NET 8+): decodes the 6-opcode
   dehydration command stream into Binary Ninja's own memory at the
   `hydrated` address the stream specifies. .NET 7 (and .NET 9/10 builds
   with dehydration disabled) have no such section -- recovery falls back
   to a brute-force 8-byte-aligned pointer scan of the whole image instead.
3. **Finds `System.Object`** by its distinctive header shape (exactly 3
   vtable slots, no base type, no interfaces, base size `0x18`), then walks
   the induced inheritance graph to a fixed point: any pointer that
   dereferences to an already-known MethodTable is assumed to be some other
   MethodTable's base-type field, letting a new MethodTable be carved out
   8 bytes before it.
4. **Names virtual methods** by BFS from `System.Object` outward
   (`ToString`/`Equals`/`GetHashCode` for slots 0-2, `Method_<slot>`
   otherwise), qualified with the owning type
   (`<Type>::<Method>`) -- only for functions that still have an
   auto-generated name, so manual/FLIRT/PDB-derived names are never
   clobbered.
5. **Identifies `System.String`** (a class directly derived from
   `System.Object` with the unique base size `0x16`) and lays out its real
   `[mt][length:i32][chars:utf16]` shape, plus SZ array instances
   (`[mt][length][padding][data]`).
6. **Annotates frozen objects** (the `FROZEN_OBJECT_REGION` section):
   compile-time string literals (labelled `dn_<text>_<addr>` with the exact
   text as a comment), SZ arrays, and boxed value types.

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `dotnet_native_aot.annotate_frozen_objects` | bool | `true` | Recover frozen strings/arrays/boxed values |
| `dotnet_native_aot.mark_rehydration_code` | bool | `false` | Leave an EOL comment on every dehydration opcode while decompressing (.NET 8+) |
| `dotnet_native_aot.auto_detect_rtr` | bool | `true` | Only show NativeAOT \| Recover Metadata when a ReadyToRun directory is actually detected (symbol lookup, then a signature scan of non-executable data segments). Turning it off makes the plain command behave like the always-shown Force variant. |

## Scripting (`api.py`)

```python
from frameworks.dotnet_native_aot import api

result = api.recover_metadata(bv)
print(result.method_tables, result.functions_named, result.strings_recovered)
for w in result.warnings:
    print("warning:", w)

# or async, from a PluginCommand:
api.recover_metadata(bv, async_run=True, on_complete=lambda r: ...)
```

`recover_metadata` also takes `annotate_frozen`, `mark_rehydration_code`,
and `log` (a `str -> None` progress callback).

## Known limitations

- **Typed cross-references are simplified**: base-type/interface pointers
  and vtable/interface array entries in the generated `<Type>_MT` struct
  are `void*`, not typed pointers to the referenced type's own struct (the
  Ghidra/IDA tools build a fully cross-referenced graph). Field names,
  offsets, sizes, and the recovered function graph are unaffected -- this
  only costs an extra click through the Types view to see what a given
  slot points at.
- **No live rename-propagation browser**: the upstream IDA plugin ships a
  side-panel browser that live-syncs with renames and can propagate a type
  rename to all its methods at once. Per this repo's UI convention (prefer
  Binary Ninja's native display over custom UI -- see `docs/adr/0024`),
  recovered types/methods are just regular BN types, data vars, and
  function symbols, browsable through BN's own Types/Symbols views; there's
  no bespoke panel.
- **Generic instantiations and interface dispatch maps** are recovered only
  as far as the base MethodTable/vtable/interface-array data goes; there is
  no attempt to reconstruct generic type arguments or synthesize
  interface-to-vtable-slot dispatch stubs beyond what's already in the
  interface pointer array.
- Tested against x86-64 and AArch64 images structurally (the metadata is
  pure data, not code, so the algorithm is architecture-independent) but
  only exercised end-to-end against x86-64 NativeAOT output; report an
  issue if AArch64 recovery misbehaves.
